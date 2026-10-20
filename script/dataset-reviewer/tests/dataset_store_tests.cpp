#include "dataset_store.h"

#include <QDir>
#include <QCryptographicHash>
#include <QFile>
#include <QLockFile>
#include <QTemporaryDir>
#include <QtTest>
#include <limits>

namespace {

const QByteArray header = QStringLiteral("图片,Small,Occluded,Blurred,No Ball,split,annotation_status,scene_review_required").toUtf8();

bool writeFile(const QString &path, const QByteArray &bytes)
{
    QFile file(path);
    return file.open(QIODevice::WriteOnly) && file.write(bytes) == bytes.size();
}

QByteArray readFile(const QString &path)
{
    QFile file(path);
    if (!file.open(QIODevice::ReadOnly))
        return QByteArray();
    return file.readAll();
}

QByteArray simpleCsv()
{
    return header + "\nshot.v1.png,0,0,0,0,train,positive,1\n";
}

QByteArray reviewCsv(const QByteArray &status="auto_label_needs_review", const QByteArray &noBall="0")
{
    return header + ",label_review_required,auto_box_count,preserved_box_count,Notes\n"
        + "shot.v1.png,0,0,0," + noBall + ",train," + status + ",1,1,1,0,keep unknown metadata\n";
}

QString createLabel(const QTemporaryDir &directory, const QByteArray &bytes)
{
    QDir().mkpath(directory.filePath(QStringLiteral("labels/train")));
    const QString path=directory.filePath(QStringLiteral("labels/train/shot.v1.txt"));
    if (!writeFile(path,bytes)) return QString();
    return path;
}

QStringList backups(const QTemporaryDir &directory)
{
    return QDir(directory.filePath(QStringLiteral(".metadata-review-backups")))
        .entryList({QStringLiteral("*.csv")}, QDir::Files);
}

} // namespace

class DatasetStoreTests : public QObject {
    Q_OBJECT

private slots:
    void imageListPreservesCanonicalStore();
    void invalidImageList_data();
    void invalidImageList();
    void uncertainLifecycle();
    void uncertainFailurePreservesSource();
    void exportSeparatesAllSplitsAndUncertain();
    void reviewedExclusionsRemainOutsideTraining();
    void exportRejectsDirtyStaleAndUnreviewed();
    void escapingUnicodeAndExtraColumnsRoundTrip();
    void flagEditBackupAndPaths();
    void externalEditRejected();
    void lockContentionRetainsEdits();
    void backupFailureRetainsEdits();
    void directReadOnlyMutationRejected();
    void malformedCsv_data();
    void malformedCsv();
    void labelsValidateNormalizedBoxes();
    void missingAndEmptyLabelsDiffer();
    void controlledApprovalPreservesMetadataAndLabels();
    void emptyApprovalRequiresNoBall();
    void missingOrInvalidLabelCannotBeApproved();
    void staleDisplayAndPostApprovalEditRejected();
    void controlledCorrectionWithMissingLabel();
    void reviewFieldsCannotBeMutatedDirectly();
    void negativeApprovalCannotSaveWithNoBallCleared();
    void positiveApprovalRequiresNoBallCleared();
    void annotationReviewRequiresSchema();
    void manualEditBacksUpAndInvalidatesApproval();
    void manualEditCreatesMissingAndEmptyLabels();
    void manualEditRejectsConflictsAndInvalidBoxes();
    void manualEditFailurePreservesLabels();
};

void DatasetStoreTests::imageListPreservesCanonicalStore()
{
    QTemporaryDir directory;
    QVERIFY(directory.isValid());
    const QByteArray csv = header + ",Notes\n"
        + QStringLiteral("first.png,0,0,0,0,train,positive,1,keep first\n"
                         "outside.png,0,0,0,0,val,positive,1,keep outside\n"
                         "足球 3.png,0,0,0,0,test,positive,1,keep last\n").toUtf8();
    const QString metadata=directory.filePath("metadata.csv"), list=directory.filePath("batch-001.txt");
    QVERIFY(writeFile(metadata,csv));
    QVERIFY(writeFile(list,QByteArray("\xEF\xBB\xBF")+QStringLiteral("足球 3.png\r\n\r\nfirst.png\r\n").toUtf8()));
    review::DatasetStore store; QString error;
    QVERIFY2(store.load(directory.path(),error),qPrintable(error));
    const auto originalRows=store.rows;
    QVector<int> selected;
    QVERIFY2(store.imageListRows(list,selected,error),qPrintable(error));
    QCOMPARE(selected,QVector<int>({2,0}));
    QCOMPARE(store.rows,originalRows);
    QCOMPARE(store.root,directory.path());
    QVERIFY(!store.isDirty());
    QCOMPARE(readFile(metadata),csv);
    QVERIFY(store.setValue(selected.first(),"Small","1"));
    QVERIFY2(store.save(error),qPrintable(error));
    review::DatasetStore reloaded;
    QVERIFY2(reloaded.load(directory.path(),error),qPrintable(error));
    QCOMPARE(reloaded.rows.size(),3);
    QCOMPARE(reloaded.rows[0],originalRows[0]);
    QCOMPARE(reloaded.rows[1],originalRows[1]);
    QCOMPARE(reloaded.value(2,"Small"),QString("1"));
    QCOMPARE(reloaded.value(2,"Notes"),QString("keep last"));
    QCOMPARE(reloaded.value(2,"scene_review_required"),QString("1"));
    QCOMPARE(reloaded.value(2,"annotation_status"),QString("positive"));
}

void DatasetStoreTests::invalidImageList_data()
{
    QTest::addColumn<QByteArray>("bytes");
    QTest::newRow("empty") << QByteArray("\r\n\n");
    QTest::newRow("duplicate") << QByteArray("shot.v1.png\nshot.v1.png\n");
    QTest::newRow("unknown") << QByteArray("shot.v1.png\nunknown.png\n");
    QTest::newRow("path-is-not-name") << QByteArray("images/train/shot.v1.png\n");
    QTest::newRow("invalid-utf8") << QByteArray("\xFF\n");
}

void DatasetStoreTests::invalidImageList()
{
    QFETCH(QByteArray,bytes);
    QTemporaryDir directory;
    QVERIFY(directory.isValid());
    QVERIFY(writeFile(directory.filePath("metadata.csv"),simpleCsv()));
    const QString list=directory.filePath("batch.txt");
    QVERIFY(writeFile(list,bytes));
    review::DatasetStore store; QString error;
    QVERIFY2(store.load(directory.path(),error),qPrintable(error));
    QVector<int> selection{99};
    QVERIFY(!store.imageListRows(list,selection,error));
    QVERIFY(!error.isEmpty());
    QCOMPARE(selection,QVector<int>({99}));
    QVERIFY(!store.isDirty());
    QVERIFY(!store.imageListRows(directory.filePath("missing.txt"),selection,error));
    QCOMPARE(selection,QVector<int>({99}));
}

void DatasetStoreTests::escapingUnicodeAndExtraColumnsRoundTrip()
{
    QTemporaryDir directory;
    QVERIFY(directory.isValid());
    const QByteArray original = QByteArray("\xEF\xBB\xBF") + header + ",Notes\r\n"
        + QStringLiteral("\"ball,选手.png\",0,1,0,0,val,positive,1,\"首行 \"\"引号\"\"\r\n次行,字段\"\r\n"
                         "plain.jpg,0,0,1,1,test,negative_confirmed,0,末尾无换行").toUtf8();
    QVERIFY(writeFile(directory.filePath(QStringLiteral("metadata.csv")), original));
    review::DatasetStore store;
    QString error;
    QVERIFY2(store.load(directory.path(), error), qPrintable(error));
    QCOMPARE(store.rows.size(), 2);
    QCOMPARE(store.value(0, QStringLiteral("图片")), QStringLiteral("ball,选手.png"));
    QCOMPARE(store.value(0, QStringLiteral("Notes")), QStringLiteral("首行 \"引号\"\r\n次行,字段"));
    QVERIFY(store.setValue(0, QStringLiteral("Small"), QStringLiteral("1")));
    QVERIFY2(store.save(error), qPrintable(error));
    const QByteArray saved = readFile(store.metadataPath);
    QVERIFY(saved.startsWith("\xEF\xBB\xBF"));
    QVERIFY(saved.contains("\r\n"));
    QVERIFY(!saved.endsWith('\n'));
    review::DatasetStore reloaded;
    QVERIFY2(reloaded.load(directory.path(), error), qPrintable(error));
    QCOMPARE(reloaded.headers, store.headers);
    QCOMPARE(reloaded.rows, store.rows);
    QCOMPARE(reloaded.value(0, QStringLiteral("Notes")), QStringLiteral("首行 \"引号\"\r\n次行,字段"));
    QCOMPARE(reloaded.value(1, QStringLiteral("Notes")), QStringLiteral("末尾无换行"));
    QCOMPARE(reloaded.value(0, QStringLiteral("Small")), QStringLiteral("1"));
    QVERIFY(!store.isDirty());
    QCOMPARE(store.dirtyCount(), 0);
    const QStringList names = backups(directory);
    QCOMPARE(names.size(), 1);
    QCOMPARE(readFile(directory.filePath(QStringLiteral(".metadata-review-backups/") + names.first())), original);
}

void DatasetStoreTests::flagEditBackupAndPaths()
{
    QTemporaryDir directory;
    const QByteArray original = simpleCsv();
    QVERIFY(writeFile(directory.filePath(QStringLiteral("metadata.csv")), original));
    QVERIFY(QDir().mkpath(directory.filePath(QStringLiteral("labels/train"))));
    const QString label = directory.filePath(QStringLiteral("labels/train/shot.v1.txt"));
    const QByteArray labelBytes("0 0.5 0.5 0.2 0.1\n");
    QVERIFY(writeFile(label, labelBytes));
    review::DatasetStore store;
    QString error;
    QVERIFY2(store.load(directory.path(), error), qPrintable(error));
    QCOMPARE(store.imagePath(0), directory.filePath(QStringLiteral("images/train/shot.v1.png")));
    QCOMPARE(store.labelPath(0), label);
    QVERIFY(store.imagePath(-1).isEmpty());
    QVERIFY(store.labelPath(1).isEmpty());
    QVERIFY(!store.setValue(0, QStringLiteral("annotation_status"), QStringLiteral("negative_confirmed")));
    QVERIFY(!store.setValue(0, QStringLiteral("split"), QStringLiteral("val")));
    QVERIFY(!store.setValue(0, QStringLiteral("Small"), QStringLiteral("2")));
    QVERIFY(!store.setValue(-1, QStringLiteral("Small"), QStringLiteral("1")));
    QVERIFY(store.setValue(0, QStringLiteral("Small"), QStringLiteral("1")));
    QVERIFY(store.rowDirty(0));
    QCOMPARE(store.dirtyCount(), 1);
    QVERIFY(store.setValue(0, QStringLiteral("Small"), QStringLiteral("0")));
    QVERIFY(!store.isDirty());
    QVERIFY(store.setValue(0, QStringLiteral("No Ball"), QStringLiteral("1")));
    QVERIFY(store.setValue(0, QStringLiteral("scene_review_required"), QStringLiteral("0")));
    QVERIFY2(store.save(error), qPrintable(error));
    QCOMPARE(readFile(label), labelBytes);
    const QByteArray firstSaved = readFile(store.metadataPath);
    QCOMPARE(backups(directory).size(), 1);
    QVERIFY2(store.save(error), qPrintable(error));
    QCOMPARE(backups(directory).size(), 1);
    QVERIFY(store.setValue(0, QStringLiteral("Blurred"), QStringLiteral("1")));
    QVERIFY2(store.save(error), qPrintable(error));
    const QStringList names = backups(directory);
    QCOMPARE(names.size(), 2);
    QVector<QByteArray> copies;
    for (const QString &name : names)
        copies.append(readFile(directory.filePath(QStringLiteral(".metadata-review-backups/") + name)));
    QVERIFY(copies.contains(original));
    QVERIFY(copies.contains(firstSaved));
    QCOMPARE(store.value(0, QStringLiteral("annotation_status")), QStringLiteral("positive"));
}

void DatasetStoreTests::externalEditRejected()
{
    QTemporaryDir directory;
    const QString metadata = directory.filePath(QStringLiteral("metadata.csv"));
    QVERIFY(writeFile(metadata, simpleCsv()));
    review::DatasetStore store;
    QString error;
    QVERIFY2(store.load(directory.path(), error), qPrintable(error));
    QVERIFY(store.setValue(0, QStringLiteral("Occluded"), QStringLiteral("1")));
    const QByteArray externallyChanged = header + "\nshot.v1.png,0,0,0,0,train,external_status,1\n";
    QVERIFY(writeFile(metadata, externallyChanged));
    QVERIFY(!store.save(error));
    QVERIFY(error.contains(QStringLiteral("外部修改")));
    QCOMPARE(readFile(metadata), externallyChanged);
    QVERIFY(store.isDirty());
    QCOMPARE(store.value(0, QStringLiteral("Occluded")), QStringLiteral("1"));
    QVERIFY(backups(directory).isEmpty());
}

void DatasetStoreTests::lockContentionRetainsEdits()
{
    QTemporaryDir directory;
    const QString metadata = directory.filePath(QStringLiteral("metadata.csv"));
    QVERIFY(writeFile(metadata, simpleCsv()));
    review::DatasetStore store;
    QString error;
    QVERIFY2(store.load(directory.path(), error), qPrintable(error));
    QVERIFY(store.setValue(0, QStringLiteral("Small"), QStringLiteral("1")));
    QLockFile lock(metadata + QStringLiteral(".review.lock"));
    QVERIFY(lock.tryLock(0));
    QVERIFY(!store.save(error));
    QVERIFY(!error.isEmpty());
    QCOMPARE(readFile(metadata), simpleCsv());
    QVERIFY(store.isDirty());
    lock.unlock();
    QVERIFY2(store.save(error), qPrintable(error));
}

void DatasetStoreTests::backupFailureRetainsEdits()
{
    QTemporaryDir directory;
    const QString metadata = directory.filePath(QStringLiteral("metadata.csv"));
    QVERIFY(writeFile(metadata, simpleCsv()));
    QVERIFY(writeFile(directory.filePath(QStringLiteral(".metadata-review-backups")), "blocked"));
    review::DatasetStore store;
    QString error;
    QVERIFY2(store.load(directory.path(), error), qPrintable(error));
    QVERIFY(store.setValue(0, QStringLiteral("Small"), QStringLiteral("1")));
    QVERIFY(!store.save(error));
    QVERIFY(error.contains(QStringLiteral("备份")));
    QCOMPARE(readFile(metadata), simpleCsv());
    QVERIFY(store.isDirty());
    QCOMPARE(store.value(0, QStringLiteral("Small")), QStringLiteral("1"));
}

void DatasetStoreTests::directReadOnlyMutationRejected()
{
    QTemporaryDir directory;
    const QString metadata = directory.filePath(QStringLiteral("metadata.csv"));
    QVERIFY(writeFile(metadata, simpleCsv()));
    review::DatasetStore store;
    QString error;
    QVERIFY2(store.load(directory.path(), error), qPrintable(error));
    store.rows[0][store.headers.indexOf(QStringLiteral("annotation_status"))] = QStringLiteral("tampered");
    QVERIFY(!store.save(error));
    QCOMPARE(readFile(metadata), simpleCsv());
    QVERIFY(store.isDirty());
}

void DatasetStoreTests::malformedCsv_data()
{
    QTest::addColumn<QByteArray>("bytes");
    QTest::newRow("unterminated-quote") << header + "\n\"shot.png,0,0,0,0,train,positive,1\n";
    QTest::newRow("quote-in-unquoted-field") << header + "\nsh\"ot.png,0,0,0,0,train,positive,1\n";
    QTest::newRow("characters-after-quote") << header + "\n\"shot.png\"x,0,0,0,0,train,positive,1\n";
    QTest::newRow("column-count") << header + "\nshot.png,0,0,0,0,train,positive\n";
    QTest::newRow("bad-flag") << header + "\nshot.png,2,0,0,0,train,positive,1\n";
    QTest::newRow("bad-label-review-flag") << header + ",label_review_required\nshot.png,0,0,0,0,train,auto_label_needs_review,1,2\n";
    QTest::newRow("bad-scene-flag") << header + "\nshot.png,0,0,0,0,train,positive,true\n";
    QTest::newRow("bad-split") << header + "\nshot.png,0,0,0,0,training,positive,1\n";
    QTest::newRow("duplicate-image") << header + "\nshot.png,0,0,0,0,train,positive,1\nshot.png,0,0,0,0,val,positive,1\n";
    QTest::newRow("image-path-traversal") << header + "\n../shot.png,0,0,0,0,train,positive,1\n";
    QTest::newRow("missing-header") << QByteArray("Small,Occluded,Blurred,No Ball,split,annotation_status,scene_review_required\n0,0,0,0,train,positive,1\n");
    QTest::newRow("duplicate-header") << header + ",Small\nshot.png,0,0,0,0,train,positive,1,0\n";
    QTest::newRow("invalid-utf8") << header + "\nshot\xFF.png,0,0,0,0,train,positive,1\n";
    QTest::newRow("empty") << QByteArray();
}

void DatasetStoreTests::malformedCsv()
{
    QFETCH(QByteArray, bytes);
    QTemporaryDir directory;
    const QString metadata = directory.filePath(QStringLiteral("metadata.csv"));
    QVERIFY(writeFile(metadata, simpleCsv()));
    review::DatasetStore store;
    QString error;
    QVERIFY2(store.load(directory.path(), error), qPrintable(error));
    const auto oldRows = store.rows;
    QVERIFY(writeFile(metadata, bytes));
    QVERIFY(!store.load(directory.path(), error));
    QVERIFY(!error.isEmpty());
    QCOMPARE(store.rows, oldRows);
}

void DatasetStoreTests::labelsValidateNormalizedBoxes()
{
    QTemporaryDir directory;
    const QString path = directory.filePath(QStringLiteral("label.txt"));
    const QByteArray raw = "0 0.5 0.25 0.1 0.2\r\n\n2\t1\t0\t1e-2\t0.3\n"
        "-1 0.5 0.5 0.1 0.1\n0.5 0.5 0.5 0.1 0.1\n"
        "0 nan 0.5 0.1 0.1\n0 1.1 0.5 0.1 0.1\n"
        "0 0.5 0.5 0 0.1\n0 0.5 0.5 0.1\n0 0.5 0.5 0.1 0.1 extra\n";
    QVERIFY(writeFile(path, raw));
    const review::LabelData labels = review::readLabels(path);
    QVERIFY(labels.exists);
    QCOMPARE(labels.raw.toUtf8(), raw);
    QCOMPARE(labels.boxes.size(), 2);
    QCOMPARE(labels.errors.size(), 7);
    QCOMPARE(labels.boxes.at(0).classId, 0);
    QCOMPARE(labels.boxes.at(0).x, 0.5);
    QCOMPARE(labels.boxes.at(0).y, 0.25);
    QCOMPARE(labels.boxes.at(0).w, 0.1);
    QCOMPARE(labels.boxes.at(0).h, 0.2);
    QCOMPARE(labels.boxes.at(1).classId, 2);
    QCOMPARE(labels.boxes.at(1).w, 0.01);
    QVERIFY(labels.errors.first().startsWith(QStringLiteral("第 4 行")));
}

void DatasetStoreTests::missingAndEmptyLabelsDiffer()
{
    QTemporaryDir directory;
    const QString path = directory.filePath(QStringLiteral("empty.txt"));
    const review::LabelData missing = review::readLabels(path);
    QVERIFY(!missing.exists);
    QVERIFY(missing.raw.isEmpty());
    QVERIFY(missing.boxes.isEmpty());
    QVERIFY(missing.errors.isEmpty());
    QVERIFY(writeFile(path, QByteArray()));
    const review::LabelData empty = review::readLabels(path);
    QVERIFY(empty.exists);
    QVERIFY(empty.raw.isEmpty());
    QVERIFY(empty.boxes.isEmpty());
    QVERIFY(empty.errors.isEmpty());
}

void DatasetStoreTests::controlledApprovalPreservesMetadataAndLabels()
{
    QTemporaryDir directory;
    const QByteArray original=reviewCsv();
    QVERIFY(writeFile(directory.filePath("metadata.csv"),original));
    const QByteArray labelBytes=QByteArray("\xEF\xBB\xBF")+"0 0.5 0.5 0.2 0.1\r\n";
    const QString label=createLabel(directory,labelBytes);
    QVERIFY(!label.isEmpty());
    review::DatasetStore store;
    QString error;
    QVERIFY2(store.load(directory.path(),error),qPrintable(error));
    const auto initial=store.rows[0];
    const review::LabelData displayed=review::readLabels(label);
    QCOMPARE(displayed.sourceHash,QCryptographicHash::hash(labelBytes,QCryptographicHash::Sha256));
    QVERIFY(!store.setValue(0,"annotation_status","reviewed_annotation"));
    QVERIFY(!store.setValue(0,"label_review_required","0"));
    QVERIFY(store.setValue(0,"Occluded","1"));
    QVERIFY2(store.approveAnnotation(0,displayed.sourceHash,error),qPrintable(error));
    QCOMPARE(store.value(0,"label_review_required"),QString("0"));
    QCOMPARE(store.value(0,"annotation_status"),QString("reviewed_annotation"));
    QVERIFY2(store.save(error),qPrintable(error));
    review::DatasetStore reloaded;
    QVERIFY2(reloaded.load(directory.path(),error),qPrintable(error));
    for (const QString &column:QStringList{QStringLiteral("图片"),"split","auto_box_count","preserved_box_count","Notes","scene_review_required"})
        QCOMPARE(reloaded.value(0,column),initial.at(store.headers.indexOf(column)));
    QCOMPARE(reloaded.value(0,"Occluded"),QString("1"));
    QCOMPARE(reloaded.value(0,"annotation_status"),QString("reviewed_annotation"));
    QCOMPARE(reloaded.value(0,"label_review_required"),QString("0"));
    QCOMPARE(readFile(label),labelBytes);
    QCOMPARE(backups(directory).size(),1);
    QVERIFY(!store.isDirty());
}

void DatasetStoreTests::emptyApprovalRequiresNoBall()
{
    QTemporaryDir directory;
    QVERIFY(writeFile(directory.filePath("metadata.csv"),reviewCsv()));
    const QString label=createLabel(directory,QByteArray());
    review::DatasetStore store;
    QString error;
    QVERIFY2(store.load(directory.path(),error),qPrintable(error));
    const auto displayed=review::readLabels(label);
    QVERIFY(!store.approveAnnotation(0,displayed.sourceHash,error));
    QVERIFY(error.contains("No Ball"));
    QVERIFY(!store.isDirty());
    QVERIFY(store.setValue(0,"No Ball","1"));
    QVERIFY2(store.approveAnnotation(0,displayed.sourceHash,error),qPrintable(error));
    QCOMPARE(store.value(0,"annotation_status"),QString("negative_confirmed"));
    QVERIFY2(store.save(error),qPrintable(error));
    QCOMPARE(readFile(label),QByteArray());
}

void DatasetStoreTests::missingOrInvalidLabelCannotBeApproved()
{
    QTemporaryDir directory;
    QVERIFY(writeFile(directory.filePath("metadata.csv"),reviewCsv()));
    review::DatasetStore store;
    QString error;
    QVERIFY2(store.load(directory.path(),error),qPrintable(error));
    QVERIFY(!store.approveAnnotation(0,QByteArray(),error));
    QVERIFY(error.contains(QStringLiteral("缺少")));
    QVERIFY(!store.isDirty());
    const QString label=createLabel(directory,"0 0.5 0.5 0 0.1\n");
    const auto displayed=review::readLabels(label);
    QVERIFY(!store.approveAnnotation(0,displayed.sourceHash,error));
    QVERIFY(error.contains(QStringLiteral("错误")));
    QVERIFY(!store.isDirty());
}

void DatasetStoreTests::staleDisplayAndPostApprovalEditRejected()
{
    QTemporaryDir directory;
    const QByteArray original=reviewCsv();
    QVERIFY(writeFile(directory.filePath("metadata.csv"),original));
    const QString label=createLabel(directory,"0 0.5 0.5 0.2 0.1\n");
    review::DatasetStore store;
    QString error;
    QVERIFY2(store.load(directory.path(),error),qPrintable(error));
    const auto oldDisplay=review::readLabels(label);
    QVERIFY(writeFile(label,"0 0.6 0.5 0.2 0.1\n"));
    QVERIFY(!store.approveAnnotation(0,oldDisplay.sourceHash,error));
    QVERIFY(error.contains(QStringLiteral("重新加载")));
    QVERIFY(!store.isDirty());
    const auto display=review::readLabels(label);
    QVERIFY2(store.approveAnnotation(0,display.sourceHash,error),qPrintable(error));
    QVERIFY(writeFile(label,"0 0.7 0.5 0.2 0.1\n"));
    QVERIFY(!store.save(error));
    QVERIFY(error.contains(QStringLiteral("审核通过后已变化")));
    QCOMPARE(readFile(directory.filePath("metadata.csv")),original);
    QVERIFY(store.isDirty());
    QVERIFY(backups(directory).isEmpty());
    const auto newDisplay=review::readLabels(label);
    QVERIFY2(store.approveAnnotation(0,newDisplay.sourceHash,error),qPrintable(error));
    QVERIFY2(store.save(error),qPrintable(error));
    QCOMPARE(readFile(label),QByteArray("0 0.7 0.5 0.2 0.1\n"));
}

void DatasetStoreTests::controlledCorrectionWithMissingLabel()
{
    QTemporaryDir directory;
    QVERIFY(writeFile(directory.filePath("metadata.csv"),reviewCsv("provided_annotation")));
    review::DatasetStore store;
    QString error;
    QVERIFY2(store.load(directory.path(),error),qPrintable(error));
    QVERIFY2(store.requireAnnotationCorrection(0,error),qPrintable(error));
    QCOMPARE(store.value(0,"annotation_status"),QString("needs_manual_bbox_annotation"));
    QCOMPARE(store.value(0,"label_review_required"),QString("1"));
    QVERIFY2(store.save(error),qPrintable(error));
    QVERIFY(!QFileInfo::exists(store.labelPath(0)));
    review::DatasetStore reloaded;
    QVERIFY2(reloaded.load(directory.path(),error),qPrintable(error));
    QCOMPARE(reloaded.value(0,"annotation_status"),QString("needs_manual_bbox_annotation"));
}

void DatasetStoreTests::reviewFieldsCannotBeMutatedDirectly()
{
    QTemporaryDir directory;
    const QByteArray original=reviewCsv();
    QVERIFY(writeFile(directory.filePath("metadata.csv"),original));
    const QString label=createLabel(directory,"0 0.5 0.5 0.2 0.1\n");
    review::DatasetStore store;
    QString error;
    QVERIFY2(store.load(directory.path(),error),qPrintable(error));
    store.rows[0][store.headers.indexOf("label_review_required")]="0";
    QVERIFY(!store.save(error));
    QCOMPARE(readFile(store.metadataPath),original);
    QVERIFY2(store.load(directory.path(),error),qPrintable(error));
    QVERIFY2(store.approveAnnotation(0,review::readLabels(label).sourceHash,error),qPrintable(error));
    store.rows[0][store.headers.indexOf("annotation_status")]="provided_annotation";
    QVERIFY(!store.save(error));
    QCOMPARE(readFile(store.metadataPath),original);
    QVERIFY2(store.load(directory.path(),error),qPrintable(error));
    QVERIFY2(store.approveAnnotation(0,review::readLabels(label).sourceHash,error),qPrintable(error));
    store.rows[0][store.headers.indexOf("auto_box_count")]="99";
    QVERIFY(!store.save(error));
    QCOMPARE(readFile(store.metadataPath),original);
}

void DatasetStoreTests::negativeApprovalCannotSaveWithNoBallCleared()
{
    QTemporaryDir directory;
    QVERIFY(writeFile(directory.filePath("metadata.csv"),reviewCsv("auto_label_needs_review","1")));
    const QString label=createLabel(directory,QByteArray());
    review::DatasetStore store;
    QString error;
    QVERIFY2(store.load(directory.path(),error),qPrintable(error));
    QVERIFY2(store.approveAnnotation(0,review::readLabels(label).sourceHash,error),qPrintable(error));
    QVERIFY(store.setValue(0,"No Ball","0"));
    QVERIFY(!store.save(error));
    QVERIFY(error.contains("No Ball"));
    QVERIFY(store.setValue(0,"No Ball","1"));
    QVERIFY2(store.save(error),qPrintable(error));
}

void DatasetStoreTests::annotationReviewRequiresSchema()
{
    QTemporaryDir directory;
    QVERIFY(writeFile(directory.filePath("metadata.csv"),simpleCsv()));
    review::DatasetStore store;
    QString error;
    QVERIFY2(store.load(directory.path(),error),qPrintable(error));
    QVERIFY(!store.approveAnnotation(0,QByteArray(),error));
    QVERIFY(!store.requireAnnotationCorrection(0,error));
    QVERIFY(!store.isDirty());
}

void DatasetStoreTests::positiveApprovalRequiresNoBallCleared()
{
    QTemporaryDir directory;
    QVERIFY(writeFile(directory.filePath("metadata.csv"),reviewCsv("auto_label_needs_review","1")));
    const QString label=createLabel(directory,"0 0.5 0.5 0.2 0.1\n");
    review::DatasetStore store;
    QString error;
    QVERIFY2(store.load(directory.path(),error),qPrintable(error));
    QVERIFY(!store.approveAnnotation(0,review::readLabels(label).sourceHash,error));
    QVERIFY(error.contains("No Ball"));
    QVERIFY(!store.isDirty());
    QVERIFY(store.setValue(0,"No Ball","0"));
    QVERIFY2(store.approveAnnotation(0,review::readLabels(label).sourceHash,error),qPrintable(error));
    QVERIFY(store.setValue(0,"No Ball","1"));
    QVERIFY(!store.save(error));
    QVERIFY(error.contains("No Ball"));
    QVERIFY(store.setValue(0,"No Ball","0"));
    QVERIFY2(store.save(error),qPrintable(error));
}

void DatasetStoreTests::manualEditBacksUpAndInvalidatesApproval()
{
    QTemporaryDir directory;
    QVERIFY(writeFile(directory.filePath("metadata.csv"),reviewCsv()));
    const QByteArray original=QByteArray("\xEF\xBB\xBF")+"0 0.5 0.5 0.2 0.1\r\n";
    const QString label=createLabel(directory,original);
    review::DatasetStore store; QString error;
    QVERIFY2(store.load(directory.path(),error),qPrintable(error));
    QVERIFY2(store.approveAnnotation(0,review::readLabels(label).sourceHash,error),qPrintable(error));
    QVERIFY2(store.save(error),qPrintable(error));
    QVERIFY(store.setValue(0,"Small","1"));
    const auto before=store.rows[0];
    QVERIFY2(store.saveLabelBoxes(0,review::readLabels(label),{{2,.6,.4,.03,.02}},error),qPrintable(error));
    const auto edited=review::readLabels(label);
    QVERIFY(edited.errors.isEmpty()); QCOMPARE(edited.boxes.size(),1);
    QCOMPARE(edited.boxes[0].classId,2); QCOMPARE(edited.boxes[0].x,.6); QCOMPARE(edited.boxes[0].w,.03);
    const auto copies=QDir(directory.filePath(".label-review-backups/train")).entryList({"*.txt"},QDir::Files);
    QCOMPARE(copies.size(),1);
    QCOMPARE(readFile(directory.filePath(".label-review-backups/train/")+copies[0]),original);
    review::DatasetStore reloaded; QVERIFY2(reloaded.load(directory.path(),error),qPrintable(error));
    QCOMPARE(reloaded.value(0,"annotation_status"),QString("needs_manual_bbox_annotation"));
    QCOMPARE(reloaded.value(0,"label_review_required"),QString("1"));
    QCOMPARE(reloaded.value(0,"Small"),QString("1"));
    for (const auto &column : QStringList{"auto_box_count","preserved_box_count","Notes","scene_review_required"})
        QCOMPARE(reloaded.value(0,column),before[store.headers.indexOf(column)]);
    QVERIFY(!store.isDirty());
    QVERIFY2(store.approveAnnotation(0,edited.sourceHash,error),qPrintable(error));
    QVERIFY2(store.save(error),qPrintable(error));
}

void DatasetStoreTests::manualEditCreatesMissingAndEmptyLabels()
{
    QTemporaryDir directory;
    QVERIFY(writeFile(directory.filePath("metadata.csv"),reviewCsv()));
    review::DatasetStore store; QString error;
    QVERIFY2(store.load(directory.path(),error),qPrintable(error));
    const QString path=store.labelPath(0);
    const auto missing=review::readLabels(path); QVERIFY(!missing.exists);
    QVERIFY2(store.saveLabelBoxes(0,missing,{{0,.5,.5,.1,.1}},error),qPrintable(error));
    const auto created=review::readLabels(path); QVERIFY(created.exists); QCOMPARE(created.boxes.size(),1);
    QVERIFY2(store.saveLabelBoxes(0,created,{},error),qPrintable(error));
    QCOMPARE(readFile(path),QByteArray());
    QVERIFY(!store.approveAnnotation(0,review::readLabels(path).sourceHash,error));
    QVERIFY(store.setValue(0,"No Ball","1"));
    QVERIFY2(store.approveAnnotation(0,review::readLabels(path).sourceHash,error),qPrintable(error));
    QVERIFY2(store.save(error),qPrintable(error));
}

void DatasetStoreTests::manualEditRejectsConflictsAndInvalidBoxes()
{
    QTemporaryDir directory;
    const QByteArray csv=reviewCsv();
    QVERIFY(writeFile(directory.filePath("metadata.csv"),csv));
    const QByteArray original="0 0.5 0.5 0.2 0.1\n";
    const QString path=createLabel(directory,original);
    review::DatasetStore store; QString error;
    QVERIFY2(store.load(directory.path(),error),qPrintable(error));
    const auto displayed=review::readLabels(path);
    QVERIFY(!store.saveLabelBoxes(0,displayed,{{0,.5,.5,0,.1}},error));
    QVERIFY(!store.saveLabelBoxes(0,displayed,{{-1,.5,.5,.1,.1}},error));
    QVERIFY(!store.saveLabelBoxes(0,displayed,{{0,std::numeric_limits<double>::quiet_NaN(),.5,.1,.1}},error));
    QVERIFY(!store.isDirty()); QCOMPARE(readFile(path),original);
    QVERIFY(writeFile(path,"0 0.7 0.5 0.2 0.1\n"));
    QVERIFY(!store.saveLabelBoxes(0,displayed,{{0,.3,.3,.1,.1}},error));
    QVERIFY(error.contains(QStringLiteral("外部修改"))); QVERIFY(!store.isDirty());
    QCOMPARE(readFile(path),QByteArray("0 0.7 0.5 0.2 0.1\n"));
    QCOMPARE(readFile(store.metadataPath),csv);
    QVERIFY(QFile::remove(path));
    QVERIFY(!store.saveLabelBoxes(0,displayed,{},error));
    const auto missing=review::readLabels(path);
    QVERIFY(writeFile(path,original));
    QVERIFY(!store.saveLabelBoxes(0,missing,{},error));
    QVERIFY(!QFileInfo::exists(directory.filePath(".label-review-backups")));
}

void DatasetStoreTests::manualEditFailurePreservesLabels()
{
    QTemporaryDir directory;
    QVERIFY(writeFile(directory.filePath("metadata.csv"),reviewCsv()));
    const QByteArray original="0 0.5 0.5 0.2 0.1\n";
    const QString path=createLabel(directory,original);
    review::DatasetStore store; QString error;
    QVERIFY2(store.load(directory.path(),error),qPrintable(error));
    const auto displayed=review::readLabels(path);
    QLockFile lock(path+".review.lock"); QVERIFY(lock.tryLock(0));
    QVERIFY(!store.saveLabelBoxes(0,displayed,{},error));
    QVERIFY(!store.isDirty()); QCOMPARE(readFile(path),original); lock.unlock();
    QVERIFY(writeFile(directory.filePath(".label-review-backups"),"blocked"));
    QVERIFY(!store.saveLabelBoxes(0,displayed,{},error));
    QVERIFY(error.contains(QStringLiteral("备份"))); QVERIFY(!store.isDirty());
    QCOMPARE(readFile(path),original);
    QVERIFY(QFile::remove(directory.filePath(".label-review-backups")));
    const QByteArray external=reviewCsv("provided_annotation");
    QVERIFY(writeFile(store.metadataPath,external));
    QVERIFY(!store.saveLabelBoxes(0,displayed,{},error));
    QVERIFY(error.contains(QStringLiteral("外部修改")));
    QCOMPARE(readFile(path),original); QCOMPARE(readFile(store.metadataPath),external);
}

void DatasetStoreTests::uncertainLifecycle()
{
    for (const QString &reason : review::DatasetStore::uncertainStatuses()) {
        QTemporaryDir directory;
        QVERIFY(writeFile(directory.filePath("metadata.csv"),reviewCsv("negative_confirmed","1")));
        const QString label=createLabel(directory,"");
        review::DatasetStore store; QString error;
        QVERIFY2(store.load(directory.path(),error),qPrintable(error));
        QVERIFY2(store.markUncertain(0,reason,error),qPrintable(error));
        QVERIFY(store.isUncertain(0));
        QCOMPARE(store.value(0,"No Ball"),QString("0"));
        QVERIFY(!store.setValue(0,"No Ball","1"));
        QVERIFY(!store.approveAnnotation(0,review::readLabels(label).sourceHash,error));
        QVERIFY(!store.saveLabelBoxes(0,review::readLabels(label),{{0,.5,.5,.1,.1}},error));
        QVERIFY2(store.save(error),qPrintable(error));
        review::DatasetStore reload;
        QVERIFY2(reload.load(directory.path(),error),qPrintable(error));
        QVERIFY(reload.isUncertain(0));
        QCOMPARE(reload.value(0,"label_review_required"),QString("1"));
        QCOMPARE(readFile(label),QByteArray());
        QVERIFY(!backups(directory).isEmpty());
        QVERIFY2(reload.requireAnnotationCorrection(0,error),qPrintable(error));
        QVERIFY(!reload.isUncertain(0));
        QVERIFY(!reload.approveAnnotation(0,review::readLabels(label).sourceHash,error));
        QVERIFY(reload.setValue(0,"No Ball","1"));
        QVERIFY2(reload.approveAnnotation(0,review::readLabels(label).sourceHash,error),qPrintable(error));
        QVERIFY2(reload.save(error),qPrintable(error));
        QCOMPARE(reload.value(0,"annotation_status"),QString("negative_confirmed"));
    }
}

void DatasetStoreTests::uncertainFailurePreservesSource()
{
    QTemporaryDir directory;
    const QByteArray original=reviewCsv();
    QVERIFY(writeFile(directory.filePath("metadata.csv"),original));
    const QByteArray boxes="0 .5 .5 .1 .1\n";
    const QString label=createLabel(directory,boxes);
    review::DatasetStore store; QString error;
    QVERIFY2(store.load(directory.path(),error),qPrintable(error));
    QVERIFY(!store.markUncertain(0,"typo",error));
    QVERIFY(!store.isDirty());
    QVERIFY(store.markUncertain(0,"temporal_only",error));
    QLockFile lock(store.metadataPath+".review.lock"); QVERIFY(lock.tryLock(0));
    QVERIFY(!store.save(error)); QVERIFY(store.isDirty());
    QCOMPARE(readFile(store.metadataPath),original); QCOMPARE(readFile(label),boxes);
    lock.unlock();
    QVERIFY(writeFile(directory.filePath(".metadata-review-backups"),"blocked"));
    QVERIFY(!store.save(error));
    QCOMPARE(readFile(store.metadataPath),original); QCOMPARE(readFile(label),boxes);
    QVERIFY(QFile::remove(directory.filePath(".metadata-review-backups")));
    QVERIFY(writeFile(store.metadataPath,original+"\n"));
    QVERIFY(!store.save(error)); QCOMPARE(readFile(label),boxes);
}

void DatasetStoreTests::exportSeparatesAllSplitsAndUncertain()
{
    QTemporaryDir directory, output;
    QString csv=QString::fromUtf8(header)+",label_review_required,source_video,source_frame_idx,eye\n";
    const QStringList statuses={"reviewed_annotation","negative_confirmed","uncertain_bbox","temporal_only","fully_occluded","severe_blur","severe_occlusion","uncertain","needs_manual_bbox_annotation"};
    for (const auto &split : QStringList{"train","val","test"}) {
        QVERIFY(QDir().mkpath(directory.filePath("images/"+split)));
        QVERIFY(QDir().mkpath(directory.filePath("labels/"+split)));
        for (int i=0;i<statuses.size();++i) {
            const QString stem=split+QString::number(i);
            csv+=QString("%1.png,0,1,1,%2,%3,%4,0,%5,match.mp4,123,left\n")
                .arg(stem,i==1?"1":"0",split,statuses[i],i<2?"0":"1");
            QVERIFY(writeFile(directory.filePath("images/"+split+'/'+stem+".png"),"image bytes"));
            // Include uncertain samples with existing, empty and missing labels.
            if (i!=3) QVERIFY(writeFile(directory.filePath("labels/"+split+'/'+stem+".txt"),i==1||i==4?"":"0 .5 .5 .1 .1\n"));
        }
    }
    QVERIFY(writeFile(directory.filePath("metadata.csv"),csv.toUtf8()));
    review::DatasetStore store; QString error;
    QVERIFY2(store.load(directory.path(),error),qPrintable(error));
    const QString target=output.filePath("snapshot");
    QVERIFY2(store.exportDataset(target,error),qPrintable(error));
    review::DatasetStore exported;
    QVERIFY2(exported.load(target,error),qPrintable(error)); QCOMPARE(exported.rows.size(),6);
    for (const auto &split : QStringList{"train","val","test"}) {
        QCOMPARE(QDir(target+"/images/"+split).entryList(QDir::Files).size(),2);
        QCOMPARE(QDir(target+"/labels/"+split).entryList(QDir::Files).size(),2);
        QVERIFY(QFileInfo::exists(target+"/uncertain/temporal_only/"+split+"/images/"+split+"3.png"));
        QVERIFY(!QFileInfo::exists(target+"/uncertain/temporal_only/"+split+"/reference_labels/"+split+"3.png.txt"));
        QCOMPARE(readFile(target+"/uncertain/uncertain_bbox/"+split+"/reference_labels/"+split+"2.png.txt"),QByteArray("0 .5 .5 .1 .1\n"));
    }
    QVERIFY(readFile(target+"/uncertain/metadata.csv").contains("match.mp4,123,left"));
    QVERIFY(readFile(target+"/export-summary.txt").contains("uncertain=18\npending=3"));
    QVERIFY(readFile(target+"/dataset.yaml").contains("test: images/test"));
    QCOMPARE(readFile(store.metadataPath),csv.toUtf8()); QVERIFY(!store.isDirty());
    QVERIFY(!store.exportDataset(target,error));
    QVERIFY(!store.exportDataset(directory.filePath("inside"),error));
    QVERIFY(!QFileInfo::exists(directory.filePath("inside")));
    QVERIFY(writeFile(directory.filePath("labels/train/train0.txt"),"bad label"));
    QVERIFY(!store.exportDataset(output.filePath("bad"),error));
    QVERIFY(!QFileInfo::exists(output.filePath("bad")));
    QVERIFY(QDir(output.path()).entryList({".review-export-*"},QDir::Dirs|QDir::Hidden|QDir::NoDotAndDotDot).isEmpty());
}

void DatasetStoreTests::reviewedExclusionsRemainOutsideTraining()
{
    QTemporaryDir directory, output;
    const QByteArray csv=header+",label_review_required,label_review_note,Notes\n"
        "ambiguous.png,0,0,1,0,train,reviewed_excluded,0,0,previous=severe_blur,keep unknown\n"
        "border.png,0,0,0,0,train,reviewed_excluded,0,0,previous=uncertain_bbox,keep unknown\n"
        "normal.png,0,0,0,0,train,reviewed_annotation,0,0,confirmed,keep unknown\n";
    QVERIFY(QDir().mkpath(directory.filePath("images/train")));
    QVERIFY(QDir().mkpath(directory.filePath("labels/train")));
    for (const auto &name : QStringList{"ambiguous","border","normal"})
        QVERIFY(writeFile(directory.filePath("images/train/"+name+".png"),"image bytes"));
    QVERIFY(writeFile(directory.filePath("labels/train/ambiguous.txt"),QByteArray()));
    const QByteArray originalBorder="0 .01 .5 .1 .2\n";
    QVERIFY(writeFile(directory.filePath("labels/train/border.txt"),originalBorder));
    QVERIFY(writeFile(directory.filePath("labels/train/normal.txt"),"0 .5 .5 .1 .1\n"));
    QVERIFY(writeFile(directory.filePath("metadata.csv"),csv));
    review::DatasetStore store; QString error;
    QVERIFY2(store.load(directory.path(),error),qPrintable(error));
    QVERIFY(!store.isUncertain(0)); QVERIFY(!store.isUncertain(1));
    // A completed exclusion must not block saving another image in a later batch.
    QVERIFY(store.setValue(2,"Small","1"));
    QVERIFY2(store.save(error),qPrintable(error));
    const QString target=output.filePath("snapshot");
    QVERIFY2(store.exportDataset(target,error),qPrintable(error));
    review::DatasetStore exported;
    QVERIFY2(exported.load(target,error),qPrintable(error)); QCOMPARE(exported.rows.size(),1);
    QCOMPARE(exported.value(0,QStringLiteral("图片")),QString("normal.png"));
    QVERIFY(!QFileInfo::exists(target+"/labels/train/ambiguous.txt"));
    QCOMPARE(readFile(target+"/excluded/reviewed/train/reference_labels/border.txt"),originalBorder);
    QVERIFY(QFileInfo::exists(target+"/excluded/reviewed/train/images/ambiguous.png"));
    const QByteArray excluded=readFile(target+"/excluded/reviewed/metadata.csv");
    QVERIFY(excluded.contains("previous=severe_blur")); QVERIFY(excluded.contains("keep unknown"));
    const QByteArray summary=readFile(target+"/export-summary.txt");
    QVERIFY(summary.contains("pending=0\nreviewed_excluded=2"));
    QCOMPARE(readFile(directory.filePath("labels/train/border.txt")),originalBorder);
}

void DatasetStoreTests::exportRejectsDirtyStaleAndUnreviewed()
{
    QTemporaryDir directory, output;
    QVERIFY(writeFile(directory.filePath("metadata.csv"),reviewCsv()));
    review::DatasetStore store; QString error;
    QVERIFY2(store.load(directory.path(),error),qPrintable(error));
    QVERIFY(store.setValue(0,"Small","1"));
    QVERIFY(!store.exportDataset(output.filePath("dirty"),error));
    QVERIFY2(store.save(error),qPrintable(error));
    // Pending samples are excluded, even with missing labels/images.
    QVERIFY2(store.exportDataset(output.filePath("pending"),error),qPrintable(error));
    QVERIFY(readFile(output.filePath("pending/export-summary.txt")).contains("pending=1"));
    QVERIFY(writeFile(store.metadataPath,reviewCsv("provided_annotation")));
    QVERIFY(!store.exportDataset(output.filePath("stale"),error));
    QVERIFY2(store.load(directory.path(),error),qPrintable(error));
    QVERIFY(store.markUncertain(0,"fully_occluded",error)); QVERIFY(store.save(error));
    QVERIFY(!store.exportDataset(output.filePath("missing-image"),error));
    QVERIFY(!QFileInfo::exists(output.filePath("missing-image")));
}

QTEST_APPLESS_MAIN(DatasetStoreTests)
#include "dataset_store_tests.moc"
