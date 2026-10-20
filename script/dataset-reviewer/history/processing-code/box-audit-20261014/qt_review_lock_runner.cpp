#include <QCoreApplication>
#include <QDateTime>
#include <QFile>
#include <QJsonArray>
#include <QJsonDocument>
#include <QLockFile>
#include <QProcess>
#include <QTextStream>
#include <QTimer>

#include <memory>
#include <vector>

// Use the reviewer's actual QLockFile protocol, rather than an incompatible
// flock or an emulated lock file. Locks stay held throughout the child process.
int main(int argc, char **argv) {
    QCoreApplication app(argc, argv);
    const QStringList args = app.arguments();
    if (args.size() < 5 || args.at(1) != "--lock-list" || args.at(3) != "--") {
        QTextStream(stderr) << "Usage: qt_review_lock_runner --lock-list paths.json -- command [arguments]\n";
        return 64;
    }
    QFile list(args.at(2));
    if (!list.open(QIODevice::ReadOnly)) return 66;
    QJsonParseError parseError;
    const QJsonDocument document = QJsonDocument::fromJson(list.readAll(), &parseError);
    if (parseError.error != QJsonParseError::NoError || !document.isArray()) return 65;
    std::vector<std::unique_ptr<QLockFile>> locks;
    QStringList heldPaths;
    for (const QJsonValue &value : document.array()) {
        if (!value.isString() || value.toString().isEmpty()) return 65;
        auto lock = std::make_unique<QLockFile>(value.toString());
        // Same defaults and zero-timeout behavior as dataset_store.cpp.
        if (!lock->tryLock(0)) {
            qint64 pid = -1;
            QString host, process;
            lock->getLockInfo(&pid, &host, &process);
            QTextStream(stderr) << "Review lock busy: " << value.toString()
                                << " (pid " << pid << ", " << process << ")\n";
            return 73;
        }
        heldPaths.append(value.toString());
        locks.push_back(std::move(lock));
    }
    QProcess child;
    child.setProcessChannelMode(QProcess::ForwardedChannels);
    child.start(args.at(4), args.mid(5));
    if (!child.waitForStarted()) return 69;
    int result = 70;
    QTimer renew;
    renew.setInterval(5000);
    // The GUI uses Qt's default 30 s stale-file threshold. Renew modification
    // times while a larger batch is running so that live long-held locks cannot
    // be mistaken for old short-save locks by the GUI's QLockFile instance.
    QObject::connect(&renew, &QTimer::timeout, [&]() {
        for (const QString &path : heldPaths) {
            QFile file(path);
            if (!file.open(QIODevice::ReadWrite)
                || !file.setFileTime(QDateTime::currentDateTimeUtc(), QFileDevice::FileModificationTime)) {
                QTextStream(stderr) << "Cannot renew live review lock: " << path << "\n";
                child.kill();
                child.waitForFinished();
                result = 74;
                app.quit();
                return;
            }
        }
    });
    QObject::connect(&child, &QProcess::finished, [&](int code, QProcess::ExitStatus status) {
        result = status == QProcess::NormalExit ? code : 70;
        app.quit();
    });
    renew.start();
    if (child.state() == QProcess::NotRunning)
        return child.exitStatus() == QProcess::NormalExit ? child.exitCode() : 70;
    app.exec();
    return result;
}
