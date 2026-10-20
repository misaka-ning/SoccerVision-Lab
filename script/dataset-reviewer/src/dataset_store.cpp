#include "dataset_store.h"

#include <QCryptographicHash>
#include <QDateTime>
#include <QDir>
#include <QFile>
#include <QFileInfo>
#include <QLockFile>
#include <QRegularExpression>
#include <QSaveFile>
#include <QSet>
#include <QTemporaryDir>
#include <QJsonArray>
#include <QJsonDocument>
#include <QStringDecoder>
#include <QUuid>

#include <cmath>
#include <limits>

namespace review {
namespace {

const QStringList flagColumns = {QStringLiteral("Small"), QStringLiteral("Occluded"),
                                 QStringLiteral("Blurred"), QStringLiteral("No Ball")};
const QStringList requiredColumns = {QStringLiteral("图片"), QStringLiteral("Small"),
    QStringLiteral("Occluded"), QStringLiteral("Blurred"), QStringLiteral("No Ball"),
    QStringLiteral("split"), QStringLiteral("annotation_status"), QStringLiteral("scene_review_required")};

bool editableColumn(const QString &column)
{
    return flagColumns.contains(column) || column == QStringLiteral("scene_review_required");
}

QByteArray hash(const QByteArray &bytes)
{
    return QCryptographicHash::hash(bytes, QCryptographicHash::Sha256);
}

bool readFile(const QString &path, QByteArray &bytes, QString &error)
{
    QFile file(path);
    if (!file.open(QIODevice::ReadOnly)) {
        error = QStringLiteral("无法读取 %1：%2").arg(path, file.errorString());
        return false;
    }
    bytes = file.readAll();
    if (file.error() != QFileDevice::NoError) {
        error = QStringLiteral("读取 %1 失败：%2").arg(path, file.errorString());
        return false;
    }
    return true;
}

// Strict RFC 4180-style fields, with LF, CRLF or CR record separators.
// A separator inside a quoted field remains part of the field's value.
bool parseCsv(const QString &text, QVector<QStringList> &records,
              QStringList &endings, QString &error)
{
    QString field;
    QStringList record;
    bool fieldStart = true;
    bool quoted = false;
    bool afterQuote = false;
    bool hasRecord = false;
    for (qsizetype i = 0; i < text.size(); ++i) {
        const QChar ch = text.at(i);
        if (ch.isNull()) {
            error = QStringLiteral("CSV 含有 NUL 字符（位置 %1）。").arg(i + 1);
            return false;
        }
        if (quoted) {
            if (ch == u'"') {
                if (i + 1 < text.size() && text.at(i + 1) == u'"') {
                    field += u'"';
                    ++i;
                } else {
                    quoted = false;
                    afterQuote = true;
                }
            } else {
                field += ch;
            }
            continue;
        }
        const bool separator = ch == u'\r' || ch == u'\n';
        if (afterQuote && ch != u',' && !separator) {
            error = QStringLiteral("CSV 引号字段结束后含有非法字符（位置 %1）。").arg(i + 1);
            return false;
        }
        if (ch == u'"') {
            if (!fieldStart) {
                error = QStringLiteral("CSV 未加引号字段中出现引号（位置 %1）。").arg(i + 1);
                return false;
            }
            quoted = true;
            fieldStart = false;
            hasRecord = true;
        } else if (ch == u',') {
            record.append(field);
            field.clear();
            fieldStart = true;
            afterQuote = false;
            hasRecord = true;
        } else if (separator) {
            QString ending(ch);
            if (ch == u'\r' && i + 1 < text.size() && text.at(i + 1) == u'\n') {
                ending += u'\n';
                ++i;
            }
            record.append(field);
            records.append(record);
            endings.append(ending);
            field.clear();
            record.clear();
            fieldStart = true;
            afterQuote = false;
            hasRecord = false;
        } else {
            field += ch;
            fieldStart = false;
            hasRecord = true;
        }
    }
    if (quoted) {
        error = QStringLiteral("CSV 引号字段未结束。");
        return false;
    }
    if (hasRecord || !record.isEmpty() || !field.isEmpty() || afterQuote) {
        record.append(field);
        records.append(record);
        endings.append(QString());
    }
    if (records.isEmpty()) {
        error = QStringLiteral("metadata.csv 为空。");
        return false;
    }
    return true;
}

bool validate(const QStringList &headers, const QVector<QStringList> &rows, QString &error)
{
    QSet<QString> columnNames;
    for (const QString &header : headers) {
        if (header.isEmpty() || columnNames.contains(header)) {
            error = QStringLiteral("CSV 列名为空或重复：%1。").arg(header);
            return false;
        }
        columnNames.insert(header);
    }
    for (const QString &column : requiredColumns) {
        if (!columnNames.contains(column)) {
            error = QStringLiteral("CSV 缺少必需列：%1。").arg(column);
            return false;
        }
    }
    QStringList binaryColumns = flagColumns;
    binaryColumns.append(QStringLiteral("scene_review_required"));
    if (columnNames.contains(QStringLiteral("label_review_required")))
        binaryColumns.append(QStringLiteral("label_review_required"));
    const int imageColumn = headers.indexOf(QStringLiteral("图片"));
    const int splitColumn = headers.indexOf(QStringLiteral("split"));
    QSet<QString> imageNames;
    for (qsizetype row = 0; row < rows.size(); ++row) {
        const QStringList &values = rows.at(row);
        if (values.size() != headers.size()) {
            error = QStringLiteral("CSV 数据行 %1 有 %2 列，应为 %3 列。")
                        .arg(row + 1).arg(values.size()).arg(headers.size());
            return false;
        }
        const QString &name = values.at(imageColumn);
        if (name.isEmpty() || name == QStringLiteral(".") || name == QStringLiteral("..")
            || name.contains(u'/') || name.contains(u'\\') || QFileInfo(name).isAbsolute()) {
            error = QStringLiteral("CSV 数据行 %1 的图片必须是单一文件名。").arg(row + 1);
            return false;
        }
        if (imageNames.contains(name)) {
            error = QStringLiteral("CSV 图片文件名重复：%1。").arg(name);
            return false;
        }
        imageNames.insert(name);
        const QString &split = values.at(splitColumn);
        if (split != QStringLiteral("train") && split != QStringLiteral("val")
            && split != QStringLiteral("test")) {
            error = QStringLiteral("CSV 数据行 %1 的 split 必须为 train、val 或 test。").arg(row + 1);
            return false;
        }
        for (const QString &column : binaryColumns) {
            const QString &value = values.at(headers.indexOf(column));
            if (value != QStringLiteral("0") && value != QStringLiteral("1")) {
                error = QStringLiteral("CSV 数据行 %1 的 %2 必须为 0 或 1。").arg(row + 1).arg(column);
                return false;
            }
        }
    }
    return true;
}

QString csvRecord(const QStringList &fields)
{
    QStringList escaped;
    escaped.reserve(fields.size());
    for (QString field : fields) {
        if (field.contains(u',') || field.contains(u'"') || field.contains(u'\r') || field.contains(u'\n')) {
            field.replace(QStringLiteral("\""), QStringLiteral("\"\""));
            field = u'"' + field + u'"';
        }
        escaped.append(field);
    }
    return escaped.join(u',');
}

} // namespace

LabelData readLabels(QString path)
{
    LabelData result;
    result.exists = QFileInfo::exists(path);
    if (!result.exists)
        return result;
    QByteArray bytes;
    QString error;
    if (!readFile(path, bytes, error)) {
        result.errors.append(error);
        return result;
    }
    result.sourceHash = hash(bytes);
    if (bytes.startsWith("\xEF\xBB\xBF"))
        bytes.remove(0, 3);
    QStringDecoder decoder(QStringDecoder::Utf8);
    result.raw = decoder(bytes);
    if (decoder.hasError()) {
        result.errors.append(QStringLiteral("标签文件不是有效 UTF-8。"));
        return result;
    }
    static const QRegularExpression whitespace(QStringLiteral("\\s+"));
    static const QRegularExpression integer(QStringLiteral("^[0-9]+$"));
    const QStringList lines = result.raw.split(u'\n');
    for (qsizetype line = 0; line < lines.size(); ++line) {
        const QString text = lines.at(line).trimmed();
        if (text.isEmpty())
            continue;
        const QStringList fields = text.split(whitespace, Qt::SkipEmptyParts);
        const auto invalid = [&result, line](const QString &reason) {
            result.errors.append(QStringLiteral("第 %1 行：%2").arg(line + 1).arg(reason));
        };
        if (fields.size() != 5) {
            invalid(QStringLiteral("YOLO 检测标签必须恰有 5 个字段。"));
            continue;
        }
        bool classOk = false;
        const qulonglong classValue = fields.at(0).toULongLong(&classOk);
        if (!integer.match(fields.at(0)).hasMatch() || !classOk
            || classValue > static_cast<qulonglong>(std::numeric_limits<int>::max())) {
            invalid(QStringLiteral("类别必须是非负整数。"));
            continue;
        }
        double values[4];
        bool valid = true;
        for (int i = 0; i < 4; ++i) {
            bool ok = false;
            values[i] = fields.at(i + 1).toDouble(&ok);
            if (!ok || !std::isfinite(values[i]) || values[i] < 0.0 || values[i] > 1.0
                || (i >= 2 && values[i] <= 0.0)) {
                valid = false;
                break;
            }
        }
        if (!valid) {
            invalid(QStringLiteral("坐标必须是有限归一化值；x/y 为 0–1，w/h 为大于 0 且不大于 1。"));
            continue;
        }
        result.boxes.append({static_cast<int>(classValue), values[0], values[1], values[2], values[3]});
    }
    return result;
}

bool DatasetStore::load(const QString &datasetRoot, QString &error)
{
    error.clear();
    const QString candidateRoot = QDir(datasetRoot).absolutePath();
    const QString candidatePath = QDir(candidateRoot).filePath(QStringLiteral("metadata.csv"));
    QByteArray bytes;
    if (!readFile(candidatePath, bytes, error))
        return false;
    QByteArray contents = bytes;
    const bool bom = contents.startsWith("\xEF\xBB\xBF");
    if (bom)
        contents.remove(0, 3);
    QStringDecoder decoder(QStringDecoder::Utf8);
    const QString text = decoder(contents);
    if (decoder.hasError()) {
        error = QStringLiteral("metadata.csv 不是有效 UTF-8。");
        return false;
    }
    QVector<QStringList> records;
    QStringList endings;
    if (!parseCsv(text, records, endings, error))
        return false;
    const QStringList candidateHeaders = records.takeFirst();
    if (!validate(candidateHeaders, records, error))
        return false;
    root = candidateRoot;
    loadedRoot_ = root;
    annotationReviews_.clear();
    metadataPath = candidatePath;
    headers = candidateHeaders;
    rows = records;
    originalHeaders_ = headers;
    originalRows_ = rows;
    loadedSourceHash_ = hash(bytes);
    loadedMetadataPath_ = metadataPath;
    recordEndings_ = endings;
    hadBom_ = bom;
    loaded_ = true;
    return true;
}

QString DatasetStore::value(int row, const QString &column) const
{
    const int index = headers.indexOf(column);
    if (row < 0 || row >= rows.size() || index < 0 || index >= rows.at(row).size())
        return QString();
    return rows.at(row).at(index);
}

bool DatasetStore::imageListRows(const QString &path, QVector<int> &selection, QString &error) const
{
    error.clear();
    QByteArray bytes;
    if (!readFile(path, bytes, error))
        return false;
    if (bytes.startsWith("\xEF\xBB\xBF"))
        bytes.remove(0, 3);
    QStringDecoder decoder(QStringDecoder::Utf8);
    const QString text = decoder(bytes);
    if (decoder.hasError()) {
        error = QStringLiteral("批次名单不是有效 UTF-8：%1").arg(path);
        return false;
    }
    QMap<QString, int> imageRows;
    for (int row = 0; row < rows.size(); ++row)
        imageRows.insert(value(row, QStringLiteral("图片")), row);
    QVector<int> candidate;
    QSet<QString> seen;
    const QStringList lines = text.split(QRegularExpression(QStringLiteral("\\r\\n|\\n|\\r")));
    for (int line = 0; line < lines.size(); ++line) {
        const QString &name = lines.at(line);
        if (name.isEmpty())
            continue;
        if (seen.contains(name)) {
            error = QStringLiteral("批次名单第 %1 行图片重复：%2").arg(line + 1).arg(name);
            return false;
        }
        if (!imageRows.contains(name)) {
            error = QStringLiteral("批次名单第 %1 行的图片不在 metadata.csv 中：%2").arg(line + 1).arg(name);
            return false;
        }
        seen.insert(name);
        candidate.append(imageRows.value(name));
    }
    if (candidate.isEmpty()) {
        error = QStringLiteral("批次名单没有图片：%1").arg(path);
        return false;
    }
    selection = candidate;
    return true;
}

bool DatasetStore::setValue(int row, const QString &column, const QString &newValue)
{
    const int index = headers.indexOf(column);
    if (!loaded_ || !editableColumn(column) || (newValue != QStringLiteral("0") && newValue != QStringLiteral("1"))
        || row < 0 || row >= rows.size() || index < 0 || index >= rows.at(row).size())
        return false;
    if (column == QStringLiteral("No Ball") && newValue == QStringLiteral("1") && isUncertain(row))
        return false;
    rows[row][index] = newValue;
    return true;
}

QString DatasetStore::imagePath(int row) const
{
    if (row < 0 || row >= rows.size())
        return QString();
    return QDir(root).filePath(QStringLiteral("images/%1/%2")
        .arg(value(row, QStringLiteral("split")), value(row, QStringLiteral("图片"))));
}

QString DatasetStore::labelPath(int row) const
{
    if (row < 0 || row >= rows.size())
        return QString();
    const QString stem = QFileInfo(value(row, QStringLiteral("图片"))).completeBaseName();
    return QDir(root).filePath(QStringLiteral("labels/%1/%2.txt")
        .arg(value(row, QStringLiteral("split")), stem));
}

bool DatasetStore::approveAnnotation(int row, const QByteArray &displayedLabelHash, QString &error)
{
    error.clear();
    if (!loaded_ || root != loadedRoot_ || row < 0 || row >= rows.size()
        || !headers.contains(QStringLiteral("label_review_required"))) {
        error = QStringLiteral("请先加载含 label_review_required 的数据集并选择图片。");
        return false;
    }
    if (isUncertain(row)) {
        error = QStringLiteral("不确定样本不能直接审核通过；请先重新复核当前帧是否可辨认、可定位或明确无球。");
        return false;
    }
    const LabelData labels = readLabels(labelPath(row));
    if (!labels.exists) {
        error = QStringLiteral("缺少 label 文件；不能将未标注图片审核通过。");
        return false;
    }
    if (!labels.errors.isEmpty()) {
        error = QStringLiteral("label 含有错误，不能审核通过：\n") + labels.errors.join(u'\n');
        return false;
    }
    if (displayedLabelHash.size() != 32 || labels.sourceHash != displayedLabelHash) {
        error = QStringLiteral("label 已变化或尚未成功读取；请重新加载当前图片并核对后再审核通过。");
        return false;
    }
    if (labels.boxes.isEmpty() && value(row, QStringLiteral("No Ball")) != QStringLiteral("1")) {
        error = QStringLiteral("空 label 只有在人工确认 No Ball = 1 后才能审核通过；有球图片请先补充目标框。");
        return false;
    }
    if (!labels.boxes.isEmpty() && value(row, QStringLiteral("No Ball")) == QStringLiteral("1")) {
        error = QStringLiteral("label 含有球框但 No Ball = 1；请先核对并修正分类或删除误框，再审核通过。");
        return false;
    }
    const QString status = labels.boxes.isEmpty() ? QStringLiteral("negative_confirmed")
                                                : QStringLiteral("reviewed_annotation");
    rows[row][headers.indexOf(QStringLiteral("annotation_status"))] = status;
    rows[row][headers.indexOf(QStringLiteral("label_review_required"))] = QStringLiteral("0");
    annotationReviews_[row] = {status, QStringLiteral("0"), labels.sourceHash};
    return true;
}

QStringList DatasetStore::uncertainStatuses()
{
    return {"uncertain", "severe_blur", "severe_occlusion", "uncertain_bbox", "temporal_only", "fully_occluded"};
}

bool DatasetStore::isUncertain(int row) const
{
    return uncertainStatuses().contains(value(row, "annotation_status"));
}

bool DatasetStore::markUncertain(int row, const QString &reason, QString &error)
{
    error.clear();
    if (!loaded_ || root != loadedRoot_ || row < 0 || row >= rows.size()
        || !headers.contains("label_review_required") || !uncertainStatuses().contains(reason)) {
        error = QStringLiteral("请选择图片和有效的不确定原因；CSV 需包含 label_review_required。");
        return false;
    }
    rows[row][headers.indexOf("annotation_status")] = reason;
    rows[row][headers.indexOf("label_review_required")] = "1";
    rows[row][headers.indexOf("No Ball")] = "0";
    rows[row][headers.indexOf("scene_review_required")] = "1";
    annotationReviews_[row] = {reason, "1", QByteArray()};
    return true;
}

bool DatasetStore::requireAnnotationCorrection(int row, QString &error)
{
    error.clear();
    if (!loaded_ || root != loadedRoot_ || row < 0 || row >= rows.size()
        || !headers.contains(QStringLiteral("label_review_required"))) {
        error = QStringLiteral("请先加载含 label_review_required 的数据集并选择图片。");
        return false;
    }
    const QString status = QStringLiteral("needs_manual_bbox_annotation");
    rows[row][headers.indexOf(QStringLiteral("annotation_status"))] = status;
    rows[row][headers.indexOf(QStringLiteral("label_review_required"))] = QStringLiteral("1");
    annotationReviews_[row] = {status, QStringLiteral("1"), QByteArray()};
    return true;
}

bool DatasetStore::validateAnnotationReviews(QString &error) const
{
    for (auto it = annotationReviews_.cbegin(); it != annotationReviews_.cend(); ++it) {
        const int row = it.key();
        const AnnotationReview &review = it.value();
        if (value(row, QStringLiteral("annotation_status")) != review.status
            || value(row, QStringLiteral("label_review_required")) != review.required) {
            error = QStringLiteral("第 %1 行的 label 审核状态未经受控审核操作修改。").arg(row + 1);
            return false;
        }
        if (review.approvedLabelHash.isEmpty())
            continue;
        const LabelData labels = readLabels(labelPath(row));
        if (!labels.exists || !labels.errors.isEmpty() || labels.sourceHash != review.approvedLabelHash) {
            error = QStringLiteral("第 %1 行的 label 在审核通过后已变化或无法读取；请重新加载、核对并重新审核。").arg(row + 1);
            return false;
        }
        if (labels.boxes.isEmpty() && value(row, QStringLiteral("No Ball")) != QStringLiteral("1")) {
            error = QStringLiteral("第 %1 行已通过的空 label 必须保持 No Ball = 1；请重新核对标注。").arg(row + 1);
            return false;
        }
        if (!labels.boxes.isEmpty() && value(row, QStringLiteral("No Ball")) == QStringLiteral("1")) {
            error = QStringLiteral("第 %1 行已通过的球框与 No Ball = 1 冲突；请重新核对标注。").arg(row + 1);
            return false;
        }
    }
    return true;
}

bool DatasetStore::saveLabelBoxes(int row, const LabelData &displayed, const QVector<Box> &boxes, QString &error)
{
    error.clear();
    if (!loaded_ || root != loadedRoot_ || headers != originalHeaders_ || rows.size() != originalRows_.size()
        || row < 0 || row >= rows.size() || !headers.contains(QStringLiteral("label_review_required"))) {
        error = QStringLiteral("请先加载含 label_review_required 的数据集并选择图片。");
        return false;
    }
    if (isUncertain(row)) {
        error = QStringLiteral("不确定样本保留原 label；请先重新复核，确认可定位后再修改框。");
        return false;
    }
    // Do not derive a write path from metadata altered outside the controlled API.
    for (const auto &column : {QStringLiteral("图片"), QStringLiteral("split")}) {
        if (value(row, column) != originalRows_[row][headers.indexOf(column)]) {
            error = QStringLiteral("图片名称或 split 已变化；无法保存 label。");
            return false;
        }
    }
    QByteArray replacement;
    for (const Box &box : boxes) {
        if (box.classId < 0 || !std::isfinite(box.x) || !std::isfinite(box.y)
            || !std::isfinite(box.w) || !std::isfinite(box.h)
            || box.x < 0 || box.x > 1 || box.y < 0 || box.y > 1
            || box.w <= 0 || box.w > 1 || box.h <= 0 || box.h > 1) {
            error = QStringLiteral("目标框无效：类别须为非负整数，坐标须为 0–1，宽高须大于 0。");
            return false;
        }
        replacement += QStringLiteral("%1 %2 %3 %4 %5\n").arg(box.classId)
            .arg(box.x, 0, 'g', 17).arg(box.y, 0, 'g', 17)
            .arg(box.w, 0, 'g', 17).arg(box.h, 0, 'g', 17).toUtf8();
    }
    const QString path = labelPath(row);
    if (!QDir().mkpath(QFileInfo(path).absolutePath())) {
        error = QStringLiteral("无法创建 label 目录。");
        return false;
    }
    QLockFile lock(path + QStringLiteral(".review.lock"));
    if (!lock.tryLock(0)) {
        error = QStringLiteral("label 正由另一审查工具保存，请稍后重试。");
        return false;
    }
    const auto unchanged = [&]() {
        const LabelData latest = readLabels(path);
        return latest.exists == displayed.exists && (!latest.exists
            || (displayed.sourceHash.size() == 32 && latest.sourceHash == displayed.sourceHash));
    };
    if (!unchanged()) {
        error = QStringLiteral("label 已被外部修改；请取消编辑、重新加载并核对后再修改。");
        return false;
    }
    QByteArray original;
    if (displayed.exists && !readFile(path, original, error)) return false;
    if (displayed.exists && hash(original) != displayed.sourceHash) {
        error = QStringLiteral("label 已被外部修改；请重新加载后再修改。");
        return false;
    }
    QSaveFile target(path);
    target.setDirectWriteFallback(false);
    if (!target.open(QIODevice::WriteOnly)
        || (displayed.exists && !target.setPermissions(QFileInfo(path).permissions()))
        || target.write(replacement) != replacement.size()) {
        error = QStringLiteral("无法准备 label 的原子保存：%1").arg(target.errorString());
        return false;
    }
    if (displayed.exists) {
        const QString directory = QDir(root).filePath(QStringLiteral(".label-review-backups/%1").arg(value(row, "split")));
        if (!QDir().mkpath(directory)) {
            error = QStringLiteral("无法创建 label 备份目录：%1").arg(directory);
            return false;
        }
        const QString backupPath = QDir(directory).filePath(QStringLiteral("%1-%2-%3.txt")
            .arg(QFileInfo(path).completeBaseName(), QDateTime::currentDateTimeUtc().toString("yyyyMMdd'T'HHmmsszzz'Z'"),
                 QUuid::createUuid().toString(QUuid::WithoutBraces)));
        QFile backup(backupPath);
        if (!backup.open(QIODevice::WriteOnly | QIODevice::NewOnly)
            || !backup.setPermissions(QFileInfo(path).permissions())
            || backup.write(original) != original.size() || !backup.flush()) {
            error = QStringLiteral("无法完整写入 label 备份：%1").arg(backup.errorString());
            if (backup.isOpen()) { backup.close(); backup.remove(); }
            return false;
        }
    }
    // Two files cannot be committed together. Persist pending review first so
    // a failed label commit never leaves edited bytes marked as approved.
    if (!requireAnnotationCorrection(row, error) || !save(error)) return false;
    if (!unchanged()) {
        error = QStringLiteral("label 在保存期间已被外部修改；未覆盖文件，请重新加载。");
        return false;
    }
    if (!target.commit()) {
        error = QStringLiteral("label 未保存（已标记待审核）：%1").arg(target.errorString());
        return false;
    }
    return true;
}

bool DatasetStore::exportDataset(const QString &destination, QString &error) const
{
    error.clear();
    if (!loaded_ || root != loadedRoot_ || metadataPath != loadedMetadataPath_ || isDirty()) {
        error = QStringLiteral("请先加载数据集并保存审核修改，再导出。");
        return false;
    }
    if (!headers.contains("label_review_required")) {
        error = QStringLiteral("导出需要 label_review_required 列和明确的人工审核结果。");
        return false;
    }
    const QFileInfo targetInfo(destination);
    const QString target = targetInfo.absoluteFilePath();
    const QString parent = targetInfo.dir().canonicalPath();
    const QString source = QFileInfo(root).canonicalFilePath();
    if (QFileInfo::exists(target) || targetInfo.isSymLink() || parent.isEmpty()
        || parent == source || parent.startsWith(source + '/')) {
        error = QStringLiteral("请选择源数据集之外、父目录已存在且尚不存在的新导出目录。");
        return false;
    }
    QLockFile lock(metadataPath + ".review.lock");
    if (!lock.tryLock(0)) { error = QStringLiteral("数据集正被保存，请稍后导出。"); return false; }
    QByteArray metadata;
    if (!readFile(metadataPath, metadata, error)) return false;
    if (hash(metadata) != loadedSourceHash_) {
        error = QStringLiteral("metadata.csv 已被外部修改，请重新加载后导出。"); return false;
    }
    QTemporaryDir stage(QDir(parent).filePath(".review-export-XXXXXX"));
    if (!stage.isValid()) { error = QStringLiteral("无法创建导出临时目录。"); return false; }
    const auto write = [&](const QString &relative, const QByteArray &bytes) {
        const QString path = QDir(stage.path()).filePath(relative);
        if (!QDir().mkpath(QFileInfo(path).absolutePath())) {
            error = QStringLiteral("无法创建导出目录：%1").arg(relative); return false;
        }
        QFile file(path);
        if (!file.open(QIODevice::WriteOnly | QIODevice::NewOnly) || file.write(bytes) != bytes.size() || !file.flush()) {
            error = QStringLiteral("无法完整写入导出文件：%1").arg(relative); return false;
        }
        return true;
    };
    QMap<QString, QByteArray> sourceHashes;
    const auto copy = [&](const QString &from, const QString &relative, const QByteArray &expected = QByteArray()) {
        QByteArray bytes;
        if (!readFile(from, bytes, error)) return false;
        const QByteArray digest = hash(bytes);
        if (!expected.isEmpty() && digest != expected) {
            error = QStringLiteral("导出期间源文件已变化：%1").arg(from); return false;
        }
        sourceHashes[from] = digest;
        return write(relative, bytes);
    };
    QString includedCsv = csvRecord(headers) + '\n', uncertainCsv = includedCsv, excludedCsv = includedCsv, reviewedExcludedCsv = includedCsv;
    QMap<QString, int> counts{{"train",0},{"val",0},{"test",0},{"uncertain",0},{"pending",0},{"reviewed_excluded",0}};
    QSet<QString> stems;
    for (int row = 0; row < rows.size(); ++row) {
        const QString status = value(row, "annotation_status"), split = value(row, "split");
        const QString name = value(row, QStringLiteral("图片"));
        const QString stem = QFileInfo(name).completeBaseName();
        const QString record = csvRecord(rows[row]) + '\n';
        if (status == "reviewed_excluded" && value(row,"label_review_required") == "0" && value(row,"scene_review_required") == "0") {
            const QString prefix = "excluded/reviewed/" + split + '/';
            if (!copy(imagePath(row), prefix + "images/" + name)) return false;
            // Human-reviewed exclusions retain the user's original boxes only
            // as references, including imperfect or incomplete annotations.
            if (QFileInfo::exists(labelPath(row)) && !copy(labelPath(row), prefix + "reference_labels/" + stem + ".txt")) return false;
            reviewedExcludedCsv += record; excludedCsv += record; ++counts["reviewed_excluded"];
            continue;
        }
        if (isUncertain(row)) {
            const QString prefix = "uncertain/" + status + '/' + split + '/';
            if (!copy(imagePath(row), prefix + "images/" + name)) return false;
            // Existing boxes are archival references only, outside YOLO labels/.
            if (QFileInfo::exists(labelPath(row)) && !copy(labelPath(row), prefix + "reference_labels/" + name + ".txt")) return false;
            uncertainCsv += record; excludedCsv += record; ++counts["uncertain"];
            continue;
        }
        const bool positive = status == "reviewed_annotation", negative = status == "negative_confirmed";
        if ((!positive && !negative) || value(row,"label_review_required") != "0" || value(row,"scene_review_required") != "0") {
            excludedCsv += record; ++counts["pending"]; continue;
        }
        const LabelData labels = readLabels(labelPath(row));
        if (!labels.exists || !labels.errors.isEmpty() || labels.sourceHash.size() != 32
            || (positive && (labels.boxes.isEmpty() || value(row,"No Ball") != "0"))
            || (negative && (!labels.boxes.isEmpty() || value(row,"No Ball") != "1"))) {
            error = QStringLiteral("已审核样本 %1 的 label 或 No Ball 状态不一致，请重新复核。").arg(name); return false;
        }
        for (const Box &box : labels.boxes) {
            if (box.classId != 0 || box.x - box.w/2 < -1e-6 || box.x + box.w/2 > 1+1e-6
                || box.y - box.h/2 < -1e-6 || box.y + box.h/2 > 1+1e-6) {
                error = QStringLiteral("%1 存在非足球类别或超出图像的框，无法导出。").arg(name); return false;
            }
        }
        const QString key = split + '/' + stem;
        if (stems.contains(key)) { error = QStringLiteral("导出 label 文件名冲突：%1").arg(key); return false; }
        stems.insert(key);
        if (!copy(imagePath(row), "images/" + split + '/' + name)
            || !copy(labelPath(row), "labels/" + key + ".txt", labels.sourceHash)) return false;
        includedCsv += record; ++counts[split];
    }
    for (const auto &split : {"train", "val", "test"}) {
        if (!QDir().mkpath(stage.path()+"/images/"+split) || !QDir().mkpath(stage.path()+"/labels/"+split)) {
            error = QStringLiteral("无法创建训练集合目录。"); return false;
        }
    }
    // An absolute YAML path avoids resolving relative to a trainer's global datasets directory.
    const QString yamlPath = QString::fromUtf8(QJsonDocument(QJsonArray{target}).toJson(QJsonDocument::Compact)).mid(1).chopped(1);
    QByteArray yaml = ("path: " + yamlPath + "\ntrain: images/train\nval: images/val\ntest: images/test\nnames:\n  0: football\n").toUtf8();
    QString report = QStringLiteral("policy_version=1\ncreated_utc=%1\nsource_metadata_sha256=%2\ntrain=%3\nval=%4\ntest=%5\nuncertain=%6\npending=%7\nreviewed_excluded=%8\n")
        .arg(QDateTime::currentDateTimeUtc().toString(Qt::ISODateWithMs), QString::fromLatin1(loadedSourceHash_.toHex()))
        .arg(counts["train"]).arg(counts["val"]).arg(counts["test"]).arg(counts["uncertain"]).arg(counts["pending"]).arg(counts["reviewed_excluded"]);
    if (!write("metadata.csv", includedCsv.toUtf8()) || !write("uncertain/metadata.csv", uncertainCsv.toUtf8())
        || !write("excluded/reviewed/metadata.csv", reviewedExcludedCsv.toUtf8())
        || !write("excluded.csv", excludedCsv.toUtf8()) || !write("dataset.yaml", yaml)
        || !write("export-summary.txt", report.toUtf8())) return false;
    // Check all copied inputs again before publishing the complete snapshot.
    sourceHashes[metadataPath] = loadedSourceHash_;
    for (auto it = sourceHashes.cbegin(); it != sourceHashes.cend(); ++it) {
        QByteArray bytes;
        if (!readFile(it.key(), bytes, error)) return false;
        if (hash(bytes) != it.value()) { error = QStringLiteral("导出期间源文件已变化：%1").arg(it.key()); return false; }
    }
    if (QFileInfo::exists(target) || !QDir().rename(stage.path(), target)) {
        error = QStringLiteral("无法发布导出目录（目标可能已存在）；未覆盖任何现有导出。"); return false;
    }
    stage.setAutoRemove(false);
    return true;
}

bool DatasetStore::isDirty() const
{
    return loaded_ && (headers != originalHeaders_ || rows != originalRows_);
}

int DatasetStore::dirtyCount() const
{
    int count = 0;
    for (int row = 0; row < qMax(rows.size(), originalRows_.size()); ++row) {
        if (row >= rows.size() || row >= originalRows_.size() || rows.at(row) != originalRows_.at(row))
            ++count;
    }
    return count;
}

bool DatasetStore::rowDirty(int row) const
{
    return row >= 0 && row < rows.size()
        && (row >= originalRows_.size() || rows.at(row) != originalRows_.at(row));
}

bool DatasetStore::save(QString &error)
{
    error.clear();
    if (!loaded_ || metadataPath != loadedMetadataPath_ || root != loadedRoot_) {
        error = QStringLiteral("请先加载数据集；保存目标不能在加载后更改。");
        return false;
    }
    if (headers != originalHeaders_ || rows.size() != originalRows_.size()) {
        error = QStringLiteral("不能更改 CSV 列、行数或行顺序。");
        return false;
    }
    if (!validate(headers, rows, error))
        return false;
    for (int row = 0; row < rows.size(); ++row) {
        if (isUncertain(row) && (value(row, "No Ball") != "0" || value(row, "label_review_required") != "1")) {
            error = QStringLiteral("不确定样本必须保持 No Ball=0 且 label_review_required=1（第 %1 行）。").arg(row + 1);
            return false;
        }
    }
    if (!validateAnnotationReviews(error))
        return false;
    for (qsizetype row = 0; row < rows.size(); ++row) {
        for (qsizetype column = 0; column < headers.size(); ++column) {
            const QString &name = headers.at(column);
            const bool controlled = annotationReviews_.contains(row)
                && (name == QStringLiteral("annotation_status") || name == QStringLiteral("label_review_required"));
            if (!editableColumn(name) && !controlled && rows.at(row).at(column) != originalRows_.at(row).at(column)) {
                error = QStringLiteral("只允许编辑四个属性标记、scene_review_required 或使用受控 label 审核；第 %1 行的 %2 已被修改。")
                    .arg(row + 1).arg(headers.at(column));
                return false;
            }
        }
    }
    QLockFile lock(metadataPath + QStringLiteral(".review.lock"));
    if (!lock.tryLock(0)) {
        error = QStringLiteral("metadata.csv 正由另一审查工具保存，请稍后重试。");
        return false;
    }
    QByteArray current;
    if (!readFile(metadataPath, current, error))
        return false;
    if (hash(current) != loadedSourceHash_) {
        error = QStringLiteral("metadata.csv 已被外部修改；为防止覆盖，请重新加载后核对并重新编辑。");
        return false;
    }
    if (!isDirty())
        return true;

    QString text = csvRecord(headers) + recordEndings_.at(0);
    for (qsizetype row = 0; row < rows.size(); ++row)
        text += csvRecord(rows.at(row)) + recordEndings_.at(row + 1);
    QByteArray replacement = text.toUtf8();
    if (hadBom_)
        replacement.prepend("\xEF\xBB\xBF");

    const QFile::Permissions permissions = QFileInfo(metadataPath).permissions();
    QSaveFile target(metadataPath);
    target.setDirectWriteFallback(false);
    if (!target.open(QIODevice::WriteOnly) || !target.setPermissions(permissions)
        || target.write(replacement) != replacement.size()) {
        error = QStringLiteral("无法准备 metadata.csv 的原子保存：%1").arg(target.errorString());
        target.cancelWriting();
        return false;
    }
    const QString backupDirectory = QDir(QFileInfo(metadataPath).absolutePath())
        .filePath(QStringLiteral(".metadata-review-backups"));
    if (!QDir().mkpath(backupDirectory)) {
        error = QStringLiteral("无法创建备份目录：%1").arg(backupDirectory);
        target.cancelWriting();
        return false;
    }
    const QString timestamp = QDateTime::currentDateTimeUtc().toString(QStringLiteral("yyyyMMdd'T'HHmmsszzz'Z'"));
    const QString backupPath = QDir(backupDirectory).filePath(QStringLiteral("metadata-%1-%2.csv")
        .arg(timestamp, QUuid::createUuid().toString(QUuid::WithoutBraces)));
    QFile backup(backupPath);
    if (!backup.open(QIODevice::WriteOnly | QIODevice::NewOnly)) {
        error = QStringLiteral("无法创建 CSV 备份：%1").arg(backup.errorString());
        target.cancelWriting();
        return false;
    }
    if (!backup.setPermissions(permissions) || backup.write(current) != current.size() || !backup.flush()) {
        error = QStringLiteral("无法完整写入 CSV 备份：%1").arg(backup.errorString());
        backup.close();
        backup.remove();
        target.cancelWriting();
        return false;
    }
    backup.close();
    QByteArray beforeCommit;
    if (!readFile(metadataPath, beforeCommit, error)) {
        target.cancelWriting();
        return false;
    }
    if (hash(beforeCommit) != loadedSourceHash_) {
        error = QStringLiteral("metadata.csv 在保存期间被外部修改；当前编辑和原始备份均已保留。");
        target.cancelWriting();
        return false;
    }
    if (!validateAnnotationReviews(error)) {
        target.cancelWriting();
        return false;
    }
    if (!target.commit()) {
        error = QStringLiteral("metadata.csv 原子保存失败；当前编辑和原始备份均已保留：%1").arg(target.errorString());
        return false;
    }
    loadedSourceHash_ = hash(replacement);
    annotationReviews_.clear();
    originalHeaders_ = headers;
    originalRows_ = rows;
    return true;
}

} // namespace review
