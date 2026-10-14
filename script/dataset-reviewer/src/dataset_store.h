#pragma once

#include <QByteArray>
#include <QMap>
#include <QString>
#include <QStringList>
#include <QVector>

namespace review {

struct Box {
    int classId;
    double x, y, w, h;
};

struct LabelData {
    bool exists = false;
    QString raw;
    QByteArray sourceHash; // SHA256 of the exact bytes read, including any UTF-8 BOM.
    QVector<Box> boxes;
    QStringList errors;
};

LabelData readLabels(QString path);

class DatasetStore {
public:
    QString root;
    QString metadataPath;
    QStringList headers;
    QVector<QStringList> rows;

    bool load(const QString &root, QString &error);
    QString value(int row, const QString &column) const;
    bool setValue(int row, const QString &column, const QString &value);
    QString imagePath(int row) const;
    QString labelPath(int row) const;
    // Only explicit label-review actions may change annotation review fields.
    // Approval is tied to the bytes displayed by the caller and rechecked on save.
    bool approveAnnotation(int row, const QByteArray &displayedLabelHash, QString &error);
    bool requireAnnotationCorrection(int row, QString &error);
    // Saves an explicit manual edit, backs up existing label bytes, and persists
    // the pending-review marker before replacing the label.
    bool saveLabelBoxes(int row, const LabelData &displayed, const QVector<Box> &boxes, QString &error);
    bool isDirty() const;
    int dirtyCount() const;
    bool rowDirty(int row) const;
    bool save(QString &error);

private:
    struct AnnotationReview {
        QString status;
        QString required;
        QByteArray approvedLabelHash;
    };
    QMap<int, AnnotationReview> annotationReviews_;
    bool validateAnnotationReviews(QString &error) const;
    QString loadedRoot_;
    QStringList originalHeaders_;
    QVector<QStringList> originalRows_;
    QByteArray loadedSourceHash_;
    QString loadedMetadataPath_;
    QStringList recordEndings_;
    bool hadBom_ = false;
    bool loaded_ = false;
};

} // namespace review
