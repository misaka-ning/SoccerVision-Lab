#include "dataset_store.h"
#include "label_editor.h"
#include <QtWidgets>
#include <QtCore/QCryptographicHash>
#include <QtCore/QTemporaryDir>
#include <cmath>
#include <functional>
#include <utility>
#ifdef REVIEW_GUI_TESTING
#include <QtTest/QTest>
#endif

using review::DatasetStore;
static const QStringList kFlags{"Small", "Occluded", "Blurred", "No Ball"};
static const QStringList kSceneNames{QStringLiteral("小目标"), QStringLiteral("遮挡"),
    QStringLiteral("运动模糊"), QStringLiteral("无球")};
static const QStringList kTitles{QStringLiteral("Small · 小目标"), QStringLiteral("Occluded · 遮挡"),
    QStringLiteral("Blurred · 运动模糊"), QStringLiteral("No Ball · 无球")};

class ImageView : public QGraphicsView {
public:
    std::function<void()> editLabel;
    ImageView() { setScene(&canvas); setBackgroundBrush(QColor("#161c26"));
        setRenderHints(QPainter::Antialiasing | QPainter::SmoothPixmapTransform);
        setDragMode(ScrollHandDrag); setTransformationAnchor(AnchorUnderMouse); setFocusPolicy(Qt::StrongFocus); }
    void showImage(const QPixmap &photo, const review::LabelData &labels, bool draw, bool preserveView=false, bool pendingReview=false, int preservedBoxes=0) {
        const QTransform priorTransform = transform();
        const QPointF priorCenter = mapToScene(viewport()->rect().center());
        const bool priorFit = autoFit;
        canvas.clear(); bounds = {}; pix = photo; labelData = labels;
        if (photo.isNull()) { canvas.addText(QStringLiteral("图片不存在或无法解码"))->setDefaultTextColor(Qt::white); return; }
        canvas.addPixmap(photo); canvas.setSceneRect(QRectF(QPointF(0, 0), photo.size()));
        for (int index=0; index<labels.boxes.size(); ++index) {
            const auto &box = labels.boxes.at(index);
            const bool provisional = pendingReview && index >= preservedBoxes;
            const QColor color(provisional ? "#ffad42" : "#50edab");
            QRectF rect((box.x-box.w/2)*photo.width(), (box.y-box.h/2)*photo.height(),
                        box.w*photo.width(), box.h*photo.height());
            bounds = bounds.isNull() ? rect : bounds.united(rect);
            if (!draw) continue;
            QPen pen(color, 2); pen.setCosmetic(true);
            canvas.addRect(rect, pen);
            const QString title = box.classId == 0 ? QStringLiteral("0 · football") : QString("class %1").arg(box.classId);
            auto *text = canvas.addSimpleText((provisional ? QStringLiteral("候选 · ") : QString()) + title);
            text->setBrush(color); text->setFlag(QGraphicsItem::ItemIgnoresTransformations);
            text->setPos(rect.left(), rect.top());
        }
        if (preserveView) { setTransform(priorTransform); centerOn(priorCenter); autoFit=priorFit; }
        else fit();
    }
    void fit() { autoFit = true; if (!pix.isNull()) { resetTransform(); fitInView(canvas.sceneRect(), Qt::KeepAspectRatio); } }
    void actualSize() { autoFit = false; resetTransform(); }
    void focusBoxes() { if (!bounds.isNull()) { autoFit = false;
        const double pad = qMax(12.0, qMax(bounds.width(), bounds.height())*.3);
        fitInView(bounds.adjusted(-pad, -pad, pad, pad).intersected(canvas.sceneRect()), Qt::KeepAspectRatio); } }
protected:
    void mouseDoubleClickEvent(QMouseEvent *event) override {
        if (event->button()==Qt::LeftButton && !pix.isNull() && editLabel) { editLabel(); event->accept(); return; }
        QGraphicsView::mouseDoubleClickEvent(event);
    }
    void resizeEvent(QResizeEvent *e) override { QGraphicsView::resizeEvent(e); if (autoFit) fit(); }
    void wheelEvent(QWheelEvent *e) override { if (pix.isNull()) return;
        autoFit = false; double factor = e->angleDelta().y() > 0 ? 1.2 : 1/1.2;
        const double zoom = transform().m11() * factor;
        if (zoom >= .03 && zoom <= 40) scale(factor, factor); e->accept(); }
private:
    QGraphicsScene canvas; QPixmap pix; review::LabelData labelData; QRectF bounds; bool autoFit = true;
};

class ReviewWindow : public QMainWindow {
public:
    DatasetStore store;
    ~ReviewWindow() override {
        // Child widgets lose focus during base-class teardown, after our shortcut
        // vector has been destroyed. Stop the global focus listener first.
        disconnect(qApp,nullptr,this,nullptr);
    }
    ReviewWindow() {
        resize(1480, 940); setWindowTitle(QStringLiteral("足球数据集审核"));
        auto *central = new QWidget; setCentralWidget(central); auto *layout = new QVBoxLayout(central);
        auto *top = new QHBoxLayout; layout->addLayout(top);
        auto *open = new QPushButton(QStringLiteral("打开数据集…")); top->addWidget(open);
        datasetPath = new QLineEdit; datasetPath->setReadOnly(true); top->addWidget(datasetPath, 1);
        saveButton = new QPushButton(QStringLiteral("保存审核 (Ctrl+S)")); top->addWidget(saveButton);
        connect(open, &QPushButton::clicked, this, [this] { if (!permitLeaving()) return;
            const auto root = QFileDialog::getExistingDirectory(this, QStringLiteral("选择包含 metadata.csv 的数据集"), store.root);
            if (root.isEmpty()) return; QString error; if (!loadDataset(root, error, imageListPath_)) QMessageBox::warning(this, QStringLiteral("无法打开"), error); });
        connect(saveButton, &QPushButton::clicked, this, [this] { saveChanges(); });

        galleryButton = new QPushButton(QStringLiteral("50张平铺 (G)")); top->addWidget(galleryButton);
        connect(galleryButton, &QPushButton::clicked, this, [this] { setGalleryMode(!galleryMode()); });

        exportButton = new QPushButton(QStringLiteral("导出审核数据集…")); top->addWidget(exportButton);
        connect(exportButton, &QPushButton::clicked, this, [this] {
            if (!saveChanges()) return;
            const QString destination = QFileDialog::getSaveFileName(this, QStringLiteral("指定新的导出目录名称"), QDir(store.root).absolutePath()+"-reviewed", QString(), nullptr, QFileDialog::DontConfirmOverwrite);
            if (destination.isEmpty()) return;
            QString error;
            if (!store.exportDataset(destination, error)) QMessageBox::warning(this, QStringLiteral("导出失败"), error);
            else QMessageBox::information(this, QStringLiteral("导出完成"), QStringLiteral("已生成审核数据集及独立 uncertain 集合。训练和标准评测请使用导出目录中的 dataset.yaml。\n")+destination);
        });

        content = new QStackedWidget; layout->addWidget(content, 1);
        auto *splitter = new QSplitter; content->addWidget(splitter);
        gallery = new QWidget; auto *galleryLayout = new QVBoxLayout(gallery);
        auto *galleryControls = new QHBoxLayout; galleryLayout->addLayout(galleryControls);
        galleryPrevious = new QPushButton(QStringLiteral("← 前50张")); galleryControls->addWidget(galleryPrevious);
        galleryPrevious->setObjectName("galleryPrevious");
        galleryCount = new QLabel; galleryControls->addWidget(galleryCount, 1);
        galleryNext = new QPushButton(QStringLiteral("后50张 →")); galleryControls->addWidget(galleryNext);
        galleryNext->setObjectName("galleryNext");
        auto *galleryHelp = new QLabel(QStringLiteral("点击有问题的图片进入修改；保存后按 G 返回平铺。只显示已勾选的场景分类；全部未勾选时留空。顶部前/后50张按钮翻页，平铺浏览不会自动审核通过。"));
        galleryHelp->setWordWrap(true); galleryLayout->addWidget(galleryHelp);
        tiles = new QListWidget; tiles->setObjectName("reviewTiles");
        tiles->setViewMode(QListView::IconMode); tiles->setResizeMode(QListView::Adjust);
        tiles->setMovement(QListView::Static); tiles->setWrapping(true); tiles->setWordWrap(true);
        tiles->setIconSize(QSize(250, 142)); tiles->setGridSize(QSize(274, 244));
        tiles->setSpacing(3); tiles->setSelectionMode(QAbstractItemView::SingleSelection);
        tiles->setEditTriggers(QAbstractItemView::NoEditTriggers);
        galleryLayout->addWidget(tiles, 1); content->addWidget(gallery);
        connect(galleryPrevious, &QPushButton::clicked, this, [this] { if (galleryPage>0) { --galleryPage; goTo(visible[galleryPage*50]); rebuildGallery(); } });
        connect(galleryNext, &QPushButton::clicked, this, [this] { if ((galleryPage+1)*50<visible.size()) { ++galleryPage; goTo(visible[galleryPage*50]); rebuildGallery(); } });
        connect(tiles, &QListWidget::itemClicked, this, [this](QListWidgetItem *item) {
            goTo(item->data(Qt::UserRole).toInt()); setGalleryMode(false); view->setFocus();
        });
        auto *left = new QWidget; auto *leftLayout = new QVBoxLayout(left);
        search = new QLineEdit; search->setPlaceholderText(QStringLiteral("搜索图片名称")); leftLayout->addWidget(search);
        auto *filters = new QHBoxLayout; leftLayout->addLayout(filters);
        splitFilter = new QComboBox; splitFilter->addItems({QStringLiteral("全部集合"), "train", "val", "test"}); filters->addWidget(splitFilter);
        sceneFilter = new QComboBox; sceneFilter->addItems({QStringLiteral("全部场景"), QStringLiteral("小目标"), QStringLiteral("遮挡"),
            QStringLiteral("运动模糊"), QStringLiteral("无球"), QStringLiteral("四项全0"), QStringLiteral("待场景复核"), QStringLiteral("缺少label"), QStringLiteral("待label审核"), QStringLiteral("不确定样本")}); filters->addWidget(sceneFilter, 1);
        count = new QLabel; leftLayout->addWidget(count);
        auto *legend = new QLabel(QStringLiteral("场景仅显示已勾选的分类")); legend->setStyleSheet("color:#66758b"); leftLayout->addWidget(legend);
        table = new QTableWidget; table->setColumnCount(3); table->setHorizontalHeaderLabels({QStringLiteral("图片"), QStringLiteral("集合"), QStringLiteral("场景")});
        table->setSelectionBehavior(QAbstractItemView::SelectRows); table->setSelectionMode(QAbstractItemView::SingleSelection);
        table->setEditTriggers(QAbstractItemView::NoEditTriggers); table->verticalHeader()->hide(); table->setAlternatingRowColors(true);
        table->horizontalHeader()->setSectionResizeMode(0, QHeaderView::Stretch);
        table->horizontalHeader()->setSectionResizeMode(1, QHeaderView::ResizeToContents);
        table->horizontalHeader()->setSectionResizeMode(2, QHeaderView::ResizeToContents);
        leftLayout->addWidget(table, 1); splitter->addWidget(left);

        auto *middle = new QWidget; auto *middleLayout = new QVBoxLayout(middle);
        caption = new QLabel(QStringLiteral("打开数据集开始审核")); caption->setWordWrap(true); middleLayout->addWidget(caption);
        auto *viewControls = new QHBoxLayout; middleLayout->addLayout(viewControls);
        drawBoxes = new QCheckBox(QStringLiteral("显示检测框 (B)")); drawBoxes->setChecked(true); viewControls->addWidget(drawBoxes);
        auto *fitButton = new QPushButton(QStringLiteral("适应窗口 (F)")); auto *native = new QPushButton("100%");
        auto *focus = new QPushButton(QStringLiteral("放大检测框")); viewControls->addWidget(fitButton); viewControls->addWidget(native); viewControls->addWidget(focus); viewControls->addStretch();
        view = new ImageView; middleLayout->addWidget(view, 1); splitter->addWidget(middle);
        view->editLabel=[this] { editCurrentLabel(); };
        connect(fitButton, &QPushButton::clicked, view, [this] { view->fit(); });
        connect(native, &QPushButton::clicked, view, [this] { view->actualSize(); });
        connect(focus, &QPushButton::clicked, view, [this] { view->focusBoxes(); });
        connect(drawBoxes, &QCheckBox::toggled, this, [this] { drawCurrent(true); });

        auto *right = new QWidget; right->setMinimumWidth(300); right->setMaximumWidth(390); auto *rightLayout = new QVBoxLayout(right);
        auto *title = new QLabel(QStringLiteral("困难场景 · 可同时选多项")); title->setStyleSheet("font-size:17px; font-weight:600"); rightLayout->addWidget(title);
        for (int i=0; i<4; ++i) { flags[i] = new QCheckBox(kTitles[i] + QString("  [%1]").arg(i+1)); rightLayout->addWidget(flags[i]);
            connect(flags[i], &QCheckBox::toggled, this, [this, i](bool value) { if (loading || current < 0) return;
                if (!store.setValue(current, kFlags[i], value ? "1" : "0")) {
                    QSignalBlocker block(flags[i]); flags[i]->setChecked(store.value(current,kFlags[i])=="1");
                }
                refreshRow(current); updateDirty(); }); }
        auto *zero = new QPushButton(QStringLiteral("全部置0")); rightLayout->addWidget(zero);
        connect(zero, &QPushButton::clicked, this, [this] { for (auto *flag : flags) flag->setChecked(false); });
        reviewNeeded = new QCheckBox(QStringLiteral("场景仍需复核")); rightLayout->addWidget(reviewNeeded);
        connect(reviewNeeded, &QCheckBox::toggled, this, [this](bool value) { if (loading || current < 0) return;
            store.setValue(current, "scene_review_required", value ? "1" : "0"); refreshRow(current); updateDirty(); });
        confirmButton = new QPushButton(QStringLiteral("确认分类并下一张 (Enter)")); rightLayout->addWidget(confirmButton);
        connect(confirmButton, &QPushButton::clicked, this, [this] { confirmCurrent(); });
        labelReviewStatus = new QLabel;
        labelReviewStatus->setWordWrap(true);
        labelReviewStatus->setTextInteractionFlags(Qt::TextSelectableByMouse);
        rightLayout->addWidget(labelReviewStatus);
        approveLabelButton = new QPushButton(QStringLiteral("label审核通过 (A)"));
        correctionButton = new QPushButton(QStringLiteral("label需修正"));
        auto *labelActions = new QHBoxLayout;
        labelActions->addWidget(approveLabelButton); labelActions->addWidget(correctionButton);
        rightLayout->addLayout(labelActions);
        connect(approveLabelButton, &QPushButton::clicked, this, [this] { approveCurrentLabel(); });
        connect(correctionButton, &QPushButton::clicked, this, [this] { requireCurrentCorrection(); });
        uncertainReason = new QComboBox;
        const QStringList reasons{QStringLiteral("不确定 · 原因待复核"), QStringLiteral("严重模糊 · 无法辨认"), QStringLiteral("严重遮挡 · 无法辨认"),
            QStringLiteral("uncertain_bbox · 边界不可靠"), QStringLiteral("temporal_only · 仅时序推断"), QStringLiteral("fully_occluded · 完全不可见")};
        const auto statuses = DatasetStore::uncertainStatuses();
        for (int i=0; i<statuses.size(); ++i) uncertainReason->addItem(reasons[i],statuses[i]);
        rightLayout->addWidget(uncertainReason);
        uncertainButton = new QPushButton(QStringLiteral("标记 uncertain 并保存")); rightLayout->addWidget(uncertainButton);
        connect(uncertainButton, &QPushButton::clicked, this, [this] { markCurrentUncertain(); });
        uncertainButton->setToolTip(QStringLiteral("看不清不等于无球。保留图像和原标签，导出时排除出普通训练与标准评测。"));
        editLabelButton = new QPushButton(QStringLiteral("手工修改label…（双击图片）")); rightLayout->addWidget(editLabelButton);
        connect(editLabelButton, &QPushButton::clicked, this, [this] { editCurrentLabel(); });
        auto *labelFiles = new QHBoxLayout;
        openLabelButton = new QPushButton(QStringLiteral("打开label文件"));
        reloadLabelButton = new QPushButton(QStringLiteral("重新加载label"));
        labelFiles->addWidget(openLabelButton); labelFiles->addWidget(reloadLabelButton);
        rightLayout->addLayout(labelFiles);
        connect(openLabelButton, &QPushButton::clicked, this, [this] {
            if (current>=0 && !QDesktopServices::openUrl(QUrl::fromLocalFile(store.labelPath(current))))
                QMessageBox::warning(this, QStringLiteral("无法打开label"), QStringLiteral("请在外部文本编辑器打开：\n")+store.labelPath(current)); });
        connect(reloadLabelButton, &QPushButton::clicked, this, [this] { if (current>=0) selectRow(current); });
        auto *nav = new QHBoxLayout; rightLayout->addLayout(nav); auto *prev = new QPushButton(QStringLiteral("← 上一张")); auto *next = new QPushButton(QStringLiteral("下一张 →")); nav->addWidget(prev); nav->addWidget(next);
        connect(prev, &QPushButton::clicked, this, [this] { navigate(-1); }); connect(next, &QPushButton::clicked, this, [this] { navigate(1); });
        status = new QLabel; status->setWordWrap(true); status->setTextInteractionFlags(Qt::TextSelectableByMouse); rightLayout->addWidget(status);
        details = new QLabel; details->setWordWrap(true); details->setTextInteractionFlags(Qt::TextSelectableByMouse); rightLayout->addWidget(details);
        reviewNote = new QPlainTextEdit; reviewNote->setReadOnly(true); reviewNote->setMaximumHeight(100);
        reviewNote->setPlaceholderText(QStringLiteral("本次复核说明")); rightLayout->addWidget(reviewNote);
        auto *labelTitle = new QLabel(QStringLiteral("label 内容（只读；橙色候选框待审核）")); rightLayout->addWidget(labelTitle);
        labelText = new QPlainTextEdit; labelText->setReadOnly(true); rightLayout->addWidget(labelText, 1);
        auto *help = new QLabel(QStringLiteral("滚轮缩放，拖动平移；双击图片修改label。\n切换图片保留未保存修改。\nCtrl+S 保存审核；Enter 确认场景分类并下一张。\nA 审核当前label通过并保存。\n绿色为保留标注；橙色为待审核候选。\n手工修改保存后，核对框与分类再审核通过。")); help->setWordWrap(true); help->setStyleSheet("color:#66758b"); rightLayout->addWidget(help);
        // Keep review controls and source details reachable on smaller displays.
        rightLayout->setSizeConstraint(QLayout::SetMinimumSize);
        labelText->setMinimumHeight(80);
        auto *rightScroll = new QScrollArea;
        rightScroll->setWidgetResizable(true); rightScroll->setFrameShape(QFrame::NoFrame);
        rightScroll->setMinimumWidth(320); rightScroll->setMaximumWidth(410);
        rightScroll->setWidget(right);
        splitter->addWidget(rightScroll); splitter->setSizes({370, 760, 340});

        connect(table, &QTableWidget::currentCellChanged, this, [this](int row, int, int, int) { if (row >= 0 && row < visible.size()) selectRow(visible[row]); });
        connect(splitFilter, &QComboBox::currentIndexChanged, this, [this] { rebuild(); });
        connect(sceneFilter, &QComboBox::currentIndexChanged, this, [this] { rebuild(); });
        searchTimer.setSingleShot(true); searchTimer.setInterval(140); connect(search, &QLineEdit::textChanged, &searchTimer, qOverload<>(&QTimer::start));
        connect(&searchTimer, &QTimer::timeout, this, [this] { rebuild(); });
        auto *saveShortcut = new QShortcut(QKeySequence::Save, this); connect(saveShortcut, &QShortcut::activated, this, [this] { saveChanges(); });
        auto *galleryShortcut = new QShortcut(QKeySequence("G"), this);
        connect(galleryShortcut, &QShortcut::activated, this, [this] {
            QWidget *focus=QApplication::focusWidget();
            if (!qobject_cast<QLineEdit*>(focus) && !qobject_cast<QPlainTextEdit*>(focus) && !qobject_cast<QTextEdit*>(focus)) setGalleryMode(!galleryMode());
        });
        auto shortcut = [this](QKeySequence key, std::function<void()> action) { auto *s = new QShortcut(key, this); sensitiveShortcuts.push_back(s); connect(s, &QShortcut::activated, this, action); };
        for (int i=0; i<4; ++i) shortcut(QKeySequence(QString::number(i+1)), [this, i] { if (current>=0) flags[i]->toggle(); });
        shortcut(QKeySequence(Qt::Key_Left), [this] { navigate(-1); }); shortcut(QKeySequence(Qt::Key_Right), [this] { navigate(1); });
        shortcut(QKeySequence(Qt::Key_Return), [this] { confirmCurrent(); }); shortcut(QKeySequence(Qt::Key_Enter), [this] { confirmCurrent(); });
        shortcut(QKeySequence("F"), [this] { view->fit(); }); shortcut(QKeySequence("B"), [this] { drawBoxes->toggle(); });
        shortcut(QKeySequence("A"), [this] { if (approveLabelButton->isEnabled()) approveCurrentLabel(); });
        connect(qApp, &QApplication::focusChanged, this, [this](QWidget *, QWidget *) { updateSensitiveShortcuts(); });
        updateDirty();
    }
    bool galleryMode() const { return content->currentWidget()==gallery; }
    bool openGalleryPage(int page, QString &error) {
        const int totalPages=(visible.size()+49)/50;
        if (page<1 || page>totalPages) {
            error=QStringLiteral("--gallery-page 超出范围：当前名单共 %1 页，请指定 1–%1。").arg(totalPages);
            return false;
        }
        goTo(visible[(page-1)*50]); setGalleryMode(true); return true;
    }
    void setGalleryMode(bool enabled) {
        if (enabled) {
            const int position=visible.indexOf(current);
            if (position>=0) galleryPage=position/50;
            rebuildGallery(); content->setCurrentWidget(gallery); tiles->setFocus();
            QTimer::singleShot(0,this,[this] { if (galleryMode() && tiles->currentItem()) tiles->scrollToItem(tiles->currentItem(),QAbstractItemView::EnsureVisible); });
        } else { content->setCurrentIndex(0); view->setFocus(); }
        galleryButton->setText(enabled ? QStringLiteral("返回单图 (G)") : QStringLiteral("← 返回50张平铺 (G)"));
        updateSensitiveShortcuts();
    }
    bool loadDataset(const QString &root, QString &error, const QString &imageListPath = QString()) {
        DatasetStore candidate;
        if (!candidate.load(root, error)) return false;
        QVector<int> selection;
        if (!imageListPath.isEmpty()) {
            if (!candidate.imageListRows(imageListPath, selection, error)) return false;
        } else {
            for (int row=0; row<candidate.rows.size(); ++row) selection.append(row);
        }
        store = std::move(candidate); scopeRows_ = std::move(selection);
        imageListPath_ = imageListPath.isEmpty() ? QString() : QFileInfo(imageListPath).absoluteFilePath();
        const QString batch = QFileInfo(imageListPath_).fileName();
        datasetPath->setText(store.root);
        datasetPath->setToolTip(imageListPath_.isEmpty() ? store.metadataPath : QStringLiteral("批次名单：%1\n保存到：%2").arg(imageListPath_,store.metadataPath));
        exportButton->setText(batch.isEmpty() ? QStringLiteral("导出审核数据集…") : QStringLiteral("导出完整审核数据集…"));
        exportButton->setToolTip(QStringLiteral("导出当前数据集内所有已通过审核的样本；不受批次名单和界面筛选影响。"));
        current = -1; search->clear(); splitFilter->setCurrentIndex(0); sceneFilter->setCurrentIndex(0); rebuild(); updateDirty(); return true;
    }
    void goTo(int row) { if (row < 0 || row >= store.rows.size()) return;
        if (!visible.contains(row)) { search->clear(); splitFilter->setCurrentIndex(0); sceneFilter->setCurrentIndex(0); rebuild(); }
        int position = visible.indexOf(row); if (position >= 0) { table->setCurrentCell(position, 0); selectRow(row); } }
    bool saveChanges(bool dialogs = true) {
        if (store.rows.isEmpty()) { statusBar()->showMessage(QStringLiteral("请先打开数据集"), 4000); return false; }
        const int position = visible.indexOf(current);
        if (!store.isDirty()) { rebuild(position); statusBar()->showMessage(QStringLiteral("没有未保存的审核修改"), 4000); return true; }
        QString error; if (!store.save(error)) { statusBar()->showMessage(QStringLiteral("保存失败，修改仍保留"));
            if (dialogs) QMessageBox::warning(this, QStringLiteral("未保存"), error); lastError = error; return false; }
        rebuild(position); updateDirty(); statusBar()->showMessage(QStringLiteral("审核已保存到 metadata.csv；原文件已备份"), 6000); return true;
    }
    bool smoke(const QString &output, QString &error) {
        QDir().mkpath(output); QJsonObject checks; checks["row_count"] = store.rows.size(); checks["qt_version"] = qVersion();
        checks["scope_count"] = scopeRows_.size(); checks["image_list"] = imageListPath_;
        // Exercise the user's complete list read-only, rather than a 50-image sub-list.
        const auto originalRows=store.rows;
        checks["gallery_requested_start_page"]=galleryPage+1;
        if (scopeRows_.size()>50) {
            if (!openGalleryPage(1,error)) return false;
            QApplication::processEvents();
            checks["real_gallery_first_page_can_advance"]=tiles->count()==50
                && !galleryPrevious->isEnabled() && galleryNext->isEnabled();
            galleryNext->click(); QApplication::processEvents();
            checks["real_gallery_second_page_has_stable_group_numbers"]=galleryPage==1
                && tiles->item(0)->data(Qt::UserRole).toInt()==scopeRows_[50]
                && tiles->item(0)->text().startsWith(QStringLiteral("第2组 · 01号"));
            grab().save(QDir(output).filePath("gallery-real-page-02.png"));
            auto *chosenItem=tiles->item(qMin(2,tiles->count()-1));
            const int chosen=chosenItem->data(Qt::UserRole).toInt();
#ifdef REVIEW_GUI_TESTING
            QTest::mouseClick(tiles->viewport(),Qt::LeftButton,Qt::NoModifier,tiles->visualItemRect(chosenItem).center());
#else
            tiles->itemClicked(chosenItem);
#endif
            checks["real_gallery_click_opens_single_image"]=!galleryMode() && current==chosen;
            setGalleryMode(true); QApplication::processEvents();
            checks["real_gallery_click_return_keeps_page_and_selection"]=galleryPage==1
                && tiles->currentItem() && tiles->currentItem()->data(Qt::UserRole).toInt()==chosen;
            const int lastPage=(scopeRows_.size()+49)/50;
            if (!openGalleryPage(lastPage,error)) return false;
            QApplication::processEvents();
            checks["real_gallery_last_page_correct_remainder"]=tiles->count()==(scopeRows_.size()-1)%50+1
                && !galleryNext->isEnabled() && galleryPrevious->isEnabled();
            grab().save(QDir(output).filePath("gallery-real-last-page.png"));
            galleryPrevious->click(); QApplication::processEvents();
            checks["real_gallery_last_page_can_go_back"]=galleryPage==lastPage-2
                && galleryNext->isEnabled();
            QString rejected;
            checks["gallery_page_out_of_range_refused"]=!openGalleryPage(lastPage+1,rejected)
                && !openGalleryPage(0,rejected);
            checks["real_gallery_browsing_preserves_all_reviews"]=store.rows==originalRows && !store.isDirty();
        }
        setGalleryMode(false);
        int supplied=-1, empty=-1, missing=-1, pending=-1;
        for (int i : scopeRows_) { auto labels = review::readLabels(store.labelPath(i));
            if (labels.exists && !labels.boxes.isEmpty() && supplied<0) supplied=i;
            if (labels.exists && labels.raw.trimmed().isEmpty() && empty<0) empty=i;
            if (!labels.exists && missing<0) missing=i;
            if (pendingLabelReview(i) && !labels.boxes.isEmpty() && pending<0) pending=i; }
        for (const auto &sample : QList<QPair<QString,int>>{{"annotated",supplied},{"negative",empty},{"missing",missing}}) {
            if (sample.second<0) {
                if (sample.first=="missing") { checks["real_missing_label_sample_available"]=false; continue; }
                error="Required smoke sample missing: "+sample.first; return false;
            }
            goTo(sample.second); QApplication::processEvents();
            if (photo.isNull()) { error="Cannot decode sample"; return false; }
            checks[sample.first+"_image"] = store.value(current, QStringLiteral("图片"));
            checks[sample.first+"_boxes"] = labelData.boxes.size();
            checks[sample.first+"_label_exists"] = labelData.exists;
            if (!grab().save(QDir(output).filePath(sample.first+".png"))) { error="Cannot save preview"; return false; }
        }
        if (pending>=0) {
            goTo(pending); QApplication::processEvents();
            checks["pending_image"]=store.value(current,QStringLiteral("图片"));
            checks["pending_boxes"]=labelData.boxes.size();
            checks["pending_review_required"]=pendingLabelReview(current);
            grab().save(QDir(output).filePath("pending-label.png"));
        }
        for (int i : scopeRows_) {
            if (store.value(i,QStringLiteral("图片"))=="frame_001719_left.png") {
                goTo(i); QApplication::processEvents();
                checks["reference_ball_image"]=store.value(i,QStringLiteral("图片"));
                checks["reference_ball_boxes"]=labelData.boxes.size();
                checks["reference_ball_pending"]=pendingLabelReview(i);
                grab().save(QDir(output).filePath("reference-ball-review.png"));
                view->focusBoxes(); QApplication::processEvents();
                grab().save(QDir(output).filePath("reference-ball-zoom.png"));
                break;
            }
        }
        goTo(supplied); view->focusBoxes(); QApplication::processEvents(); grab().save(QDir(output).filePath("zoom.png"));
        const double zoom = view->transform().m11(); drawBoxes->setChecked(false);
        checks["overlay_toggle_preserves_zoom"] = qFuzzyCompare(zoom,view->transform().m11()); drawBoxes->setChecked(true);
        checks["real_metadata_not_edited"] = !store.isDirty();
        QTemporaryDir fixture; if (!fixture.isValid()) { error="Cannot create fixture"; return false; }
        const QString split = store.value(supplied,"split"), name=store.value(supplied,QStringLiteral("图片"));
        QDir().mkpath(fixture.path()+"/images/"+split); QDir().mkpath(fixture.path()+"/labels/"+split);
        QFile::copy(store.imagePath(supplied), fixture.path()+"/images/"+split+"/"+name);
        const QString fixtureLabel = fixture.path()+"/labels/"+split+"/"+QFileInfo(name).completeBaseName()+".txt";
        QFile::copy(store.labelPath(supplied), fixtureLabel);
        auto quote = [](QString s) { s.replace('"',"\"\""); return '"'+s+'"'; };
        QStringList fixtureHeaders=store.headers, fixtureRow=store.rows[supplied];
        const auto fixtureField=[&](const QString &name,const QString &value) {
            int index=fixtureHeaders.indexOf(name);
            if (index<0) { fixtureHeaders<<name; fixtureRow<<value; }
            else fixtureRow[index]=value;
        };
        fixtureField("label_review_required","1");
        fixtureField("auto_box_count",QString::number(review::readLabels(fixtureLabel).boxes.size()));
        fixtureField("preserved_box_count","0");
        QStringList h, row; for (int c=0;c<fixtureHeaders.size();++c) { h<<quote(fixtureHeaders[c]); row<<quote(fixtureRow[c]); }
        QFile csv(fixture.path()+"/metadata.csv"); if (!csv.open(QIODevice::WriteOnly)) { error="Fixture CSV failed"; return false; }
        csv.write(QByteArray("\xEF\xBB\xBF")+(h.join(',')+"\r\n"+row.join(',')+"\r\n").toUtf8()); csv.close();
        // Exercise batch navigation and saving against one canonical, multi-row store.
        {
            QTemporaryDir batchFixture;
            if (!batchFixture.isValid()) { error="Cannot create batch fixture"; return false; }
            QDir().mkpath(batchFixture.path()+"/images/"+split);
            QDir().mkpath(batchFixture.path()+"/labels/"+split);
            const QStringList names{name,"outside-batch.png","selected-last.png"};
            QString batchCsv=h.join(',')+"\n";
            for (const auto &image : names) {
                auto values=fixtureRow; values[fixtureHeaders.indexOf(QStringLiteral("图片"))]=image;
                QStringList escaped; for (const auto &value : values) escaped<<quote(value);
                batchCsv+=escaped.join(',')+"\n";
                if (!QFile::copy(store.imagePath(supplied),batchFixture.path()+"/images/"+split+"/"+image)
                    || !QFile::copy(store.labelPath(supplied),batchFixture.path()+"/labels/"+split+"/"+QFileInfo(image).completeBaseName()+".txt")) {
                    error="Cannot populate batch fixture"; return false;
                }
            }
            QFile metadata(batchFixture.filePath("metadata.csv"));
            if (!metadata.open(QIODevice::WriteOnly) || metadata.write(batchCsv.toUtf8())<0) { error="Cannot write batch fixture"; return false; }
            metadata.close();
            const QString listPath=batchFixture.filePath("batch-001.txt");
            QFile list(listPath);
            if (!list.open(QIODevice::WriteOnly) || list.write((names[2]+"\n"+names[0]+"\n").toUtf8())<0) { error="Cannot write batch list"; return false; }
            list.close();
            ReviewWindow batchProbe;
            if (!batchProbe.loadDataset(batchFixture.path(),error,listPath)) return false;
            const auto outside=batchProbe.store.rows[1];
            checks["batch_list_order_and_count"] = batchProbe.visible==QVector<int>({2,0})
                && batchProbe.current==2 && batchProbe.store.rows.size()==3
                && batchProbe.count->text().contains(QStringLiteral("本批 2 张"))
                && batchProbe.windowTitle().contains("batch-001.txt");
            batchProbe.goTo(1);
            checks["batch_navigation_stays_in_scope"] = batchProbe.current==2 && batchProbe.visible==QVector<int>({2,0});
            batchProbe.sceneFilter->setCurrentIndex(7);
            batchProbe.sceneFilter->setCurrentIndex(0);
            checks["batch_filters_keep_scope"] = batchProbe.visible==QVector<int>({2,0});
            batchProbe.flags[0]->click();
            if (!batchProbe.saveChanges(false)) { error=batchProbe.lastError; return false; }
            DatasetStore batchReload;
            if (!batchReload.load(batchFixture.path(),error)) return false;
            checks["batch_save_preserves_full_metadata"] = batchReload.rows.size()==3 && batchReload.rows[1]==outside
                && batchReload.value(2,"Small")==batchProbe.store.value(2,"Small")
                && batchReload.value(2,"label_review_required")=="1"
                && batchProbe.store.metadataPath==batchFixture.filePath("metadata.csv");
            batchProbe.show(); QApplication::processEvents();
            batchProbe.grab().save(QDir(output).filePath("batch-filter.png"));
            batchProbe.setGalleryMode(true); QApplication::processEvents();
            checks["gallery_keeps_batch_scope_and_order"] = batchProbe.tiles->count()==2
                && batchProbe.tiles->item(0)->data(Qt::UserRole).toInt()==2
                && batchProbe.tiles->item(1)->data(Qt::UserRole).toInt()==0
                && batchProbe.tiles->item(0)->text().startsWith(QStringLiteral("第1组 · 01号"))
                && batchProbe.tiles->item(1)->text().startsWith(QStringLiteral("第1组 · 02号"));
            const auto batchBeforeClick=batchProbe.store.rows;
#ifdef REVIEW_GUI_TESTING
            QTest::mouseClick(batchProbe.tiles->viewport(),Qt::LeftButton,Qt::NoModifier,
                batchProbe.tiles->visualItemRect(batchProbe.tiles->item(1)).center());
#else
            batchProbe.tiles->itemClicked(batchProbe.tiles->item(1));
#endif
            checks["gallery_click_opens_selected_image_without_approval"] = !batchProbe.galleryMode()
                && batchProbe.current==0 && batchProbe.store.rows==batchBeforeClick && !batchProbe.store.isDirty();
            const QString previousSmall=batchProbe.store.value(0,"Small");
            batchProbe.flags[0]->setChecked(previousSmall!="1");
            if (!batchProbe.saveChanges(false)) { error=batchProbe.lastError; return false; }
            batchProbe.setGalleryMode(true); QApplication::processEvents();
            checks["gallery_return_refreshes_edited_metadata"] = batchProbe.tiles->currentItem()
                && batchProbe.tiles->currentItem()->data(Qt::UserRole).toInt()==0
                && (batchProbe.tiles->currentItem()->text().contains(QStringLiteral("小目标"))==(batchProbe.store.value(0,"Small")=="1"))
                && batchProbe.store.value(0,"label_review_required")=="1";
            const bool approvedBefore=batchProbe.store.value(0,"label_review_required")=="0";
#ifdef REVIEW_GUI_TESTING
            batchProbe.activateWindow(); batchProbe.tiles->setFocus(); QTest::qWait(40);
            QTest::keyClick(batchProbe.tiles,Qt::Key_A); QTest::keyClick(batchProbe.tiles,Qt::Key_1);
#endif
            checks["gallery_shortcuts_do_not_approve_hidden_image"] = !approvedBefore
                && batchProbe.store.value(0,"label_review_required")=="1" && !batchProbe.store.isDirty();
            batchProbe.grab().save(QDir(output).filePath("gallery-batch.png"));
        }
        {
            // A 53-image temporary dataset proves the 50-image boundary and stable numbering.
            QTemporaryDir gridFixture;
            if (!gridFixture.isValid()) { error="Cannot create gallery fixture"; return false; }
            QDir().mkpath(gridFixture.path()+"/images/"+split); QDir().mkpath(gridFixture.path()+"/labels/"+split);
            QString gridCsv=h.join(',')+"\n";
            for (int number=1;number<=53;++number) {
                const QString image=QString("tile-%1.png").arg(number,3,10,QChar('0'));
                auto values=fixtureRow; values[fixtureHeaders.indexOf(QStringLiteral("图片"))]=image;
                for (const auto &flag:kFlags) values[fixtureHeaders.indexOf(flag)]="0";
                values[fixtureHeaders.indexOf("Small")]=number==53 ? "1" : "0";
                if (number==52) {
                    values[fixtureHeaders.indexOf("Occluded")]="1";
                    values[fixtureHeaders.indexOf("Blurred")]="1";
                }
                QStringList escaped; for (const auto &value:values) escaped<<quote(value); gridCsv+=escaped.join(',')+"\n";
                if (!QFile::copy(store.imagePath(supplied),gridFixture.path()+"/images/"+split+"/"+image)
                    || !QFile::copy(store.labelPath(supplied),gridFixture.path()+"/labels/"+split+"/"+QFileInfo(image).completeBaseName()+".txt")) {
                    error="Cannot populate gallery fixture"; return false;
                }
            }
            QFile metadata(gridFixture.filePath("metadata.csv"));
            if (!metadata.open(QIODevice::WriteOnly) || metadata.write(gridCsv.toUtf8())<0) { error="Cannot write gallery fixture"; return false; }
            metadata.close(); ReviewWindow gridProbe;
            if (!gridProbe.loadDataset(gridFixture.path(),error)) return false;
            gridProbe.show(); gridProbe.setGalleryMode(true); QApplication::processEvents();
            checks["gallery_first_page_has_50_images"] = gridProbe.tiles->count()==50
                && !gridProbe.galleryPrevious->isEnabled() && gridProbe.galleryNext->isEnabled();
            checks["gallery_zero_flags_are_blank"]=gridProbe.sceneSummary(0).isEmpty()
                && gridProbe.tiles->item(0)->text().split('\n').value(2).isEmpty();
            gridProbe.grab().save(QDir(output).filePath("gallery-50.png"));
            gridProbe.goTo(49); gridProbe.setGalleryMode(false); gridProbe.setGalleryMode(true); QApplication::processEvents();
            checks["gallery_return_keeps_selection_visible"] = gridProbe.tiles->currentItem()
                && gridProbe.tiles->currentItem()->data(Qt::UserRole).toInt()==49
                && gridProbe.tiles->viewport()->rect().intersects(gridProbe.tiles->visualItemRect(gridProbe.tiles->currentItem()));
            gridProbe.galleryNext->click(); QApplication::processEvents();
            checks["gallery_last_page_has_remaining_3"] = gridProbe.tiles->count()==3
                && gridProbe.tiles->item(0)->text().startsWith(QStringLiteral("第2组 · 01号"))
                && !gridProbe.galleryNext->isEnabled() && gridProbe.galleryPrevious->isEnabled();
            checks["gallery_selected_flags_use_chinese_only"]=gridProbe.sceneSummary(51)==QStringLiteral("遮挡 · 运动模糊")
                && gridProbe.sceneSummary(52)==QStringLiteral("小目标")
                && gridProbe.tiles->item(1)->text().split('\n').value(2)==QStringLiteral("遮挡 · 运动模糊")
                && gridProbe.table->item(51,2)->text()==QStringLiteral("遮挡 · 运动模糊")
                && gridProbe.tiles->item(1)->toolTip().contains(QStringLiteral("遮挡 · 运动模糊"));
            gridProbe.sceneFilter->setCurrentIndex(1); QApplication::processEvents();
            checks["gallery_filter_keeps_original_image_number"] = gridProbe.tiles->count()==1
                && gridProbe.tiles->item(0)->text().startsWith(QStringLiteral("第2组 · 03号")) && !gridProbe.store.isDirty();
        }
        ReviewWindow probe; if (!probe.loadDataset(fixture.path(), error)) return false;
        checks["pending_label_not_automatically_approved"] = probe.store.value(0,"label_review_required")=="1" && !probe.store.isDirty();
        const QString prior = probe.store.value(0,"Blurred"); probe.flags[2]->click();
        checks["checkbox_changes_metadata_state"] = probe.store.value(0,"Blurred") != prior && probe.store.isDirty();
        if (!probe.saveChanges(false)) { error=probe.lastError; return false; }
        DatasetStore reload; if (!reload.load(fixture.path(), error)) return false;
        checks["ui_save_roundtrip"] = reload.value(0,"Blurred") == (prior=="1" ? "0" : "1");
        checks["annotation_status_preserved"] = reload.value(0,"annotation_status") == store.value(supplied,"annotation_status");
        QFile original(store.labelPath(supplied)), saved(fixtureLabel); original.open(QIODevice::ReadOnly); saved.open(QIODevice::ReadOnly);
        checks["label_readonly"] = original.readAll()==saved.readAll();
        // Verify a saved edit refreshes active filters, without losing the edit.
        probe.flags[0]->setChecked(true); if (!probe.saveChanges(false)) { error=probe.lastError; return false; }
        probe.sceneFilter->setCurrentIndex(1); probe.flags[0]->setChecked(false);
        if (!probe.saveChanges(false)) { error=probe.lastError; return false; }
        checks["saved_filter_refresh"] = probe.visible.isEmpty() && probe.current == -1;
        probe.sceneFilter->setCurrentIndex(0);
#ifdef REVIEW_GUI_TESTING
        setEnabled(false); probe.show(); probe.activateWindow(); QTest::qWait(40);
        QStringList before; for (const auto &flag:kFlags) before << probe.store.value(0,flag);
        probe.search->setFocus(); QTest::keyClicks(probe.search,"1234"); QTest::qWait(180);
        QStringList after; for (const auto &flag:kFlags) after << probe.store.value(0,flag);
        checks["search_typing_does_not_toggle_flags"] = before==after && probe.search->text()=="1234";
        probe.search->clear(); QTest::qWait(180); probe.view->setFocus();
        const auto beforeToggle=probe.store.value(0,"Blurred"); QTest::keyClick(probe.view,Qt::Key_3);
        checks["image_numeric_shortcut"] = probe.store.value(0,"Blurred")!=beforeToggle;
        QTest::keyClick(probe.view,Qt::Key_3);
        checks["real_metadata_not_edited"] = !store.isDirty();
#endif
        probe.sceneFilter->setCurrentIndex(8);
        checks["pending_label_filter"]=probe.visible.size()==1 && probe.current==0;
        probe.show(); QApplication::processEvents();
        probe.grab().save(QDir(output).filePath("pending-fixture.png"));
        const auto replaceFixtureLabel=[&](const QByteArray &bytes) {
            QFile file(fixtureLabel); return file.open(QIODevice::WriteOnly) && file.write(bytes)==bytes.size();
        };
        QFile beforeEdit(fixtureLabel); beforeEdit.open(QIODevice::ReadOnly);
        const QByteArray fixtureLabelBytes=beforeEdit.readAll(); beforeEdit.close();
        if (!replaceFixtureLabel(fixtureLabelBytes+"\n")) { error="Cannot modify fixture label"; return false; }
        checks["ui_stale_label_refused"] = !probe.approveCurrentLabel(false)
            && probe.store.value(0,"label_review_required")=="1" && !probe.store.isDirty();
        probe.approveLabelButton->click();
        checks["ui_explicit_label_approval_saved"] = probe.store.value(0,"label_review_required")=="0"
            && probe.store.value(0,"annotation_status")=="reviewed_annotation" && !probe.store.isDirty();
        checks["approved_label_leaves_pending_filter"] = probe.visible.isEmpty() && probe.current==-1;
        probe.sceneFilter->setCurrentIndex(0); probe.goTo(0); probe.correctionButton->click();
        checks["ui_label_correction_saved"] = probe.store.value(0,"label_review_required")=="1"
            && probe.store.value(0,"annotation_status")=="needs_manual_bbox_annotation" && !probe.store.isDirty();
        if (!replaceFixtureLabel(QByteArray())) { error="Cannot empty fixture label"; return false; }
        probe.selectRow(0); probe.flags[3]->setChecked(false);
        if (!probe.saveChanges(false)) { error=probe.lastError; return false; }
        checks["ui_empty_positive_label_refused"] = !probe.approveCurrentLabel(false)
            && probe.store.value(0,"label_review_required")=="1" && !probe.store.isDirty();
        probe.flags[3]->setChecked(true); probe.approveLabelButton->click();
        checks["ui_negative_label_approval_saved"] = probe.store.value(0,"label_review_required")=="0"
            && probe.store.value(0,"annotation_status")=="negative_confirmed" && !probe.store.isDirty();
        if (!QFile::remove(fixtureLabel)) { error="Cannot remove fixture label"; return false; }
        probe.selectRow(0);
        checks["ui_missing_label_refused"] = !probe.approveCurrentLabel(false)
            && !probe.store.isDirty();
        probe.correctionButton->click();
        checks["ui_missing_label_can_require_correction"] = probe.store.value(0,"label_review_required")=="1"
            && probe.store.value(0,"annotation_status")=="needs_manual_bbox_annotation" && !probe.store.isDirty();
#ifdef REVIEW_GUI_TESTING
        // Exercise the actual modal entry point and canvas events on the fixture.
        probe.flags[3]->setChecked(false); if (!probe.saveChanges(false)) { error=probe.lastError; return false; }
        QTimer::singleShot(0,&probe,[&] {
            auto *editor=dynamic_cast<LabelEditor*>(QApplication::activeModalWidget());
            if (!editor) { checks["manual_editor_opened"]=false; return; }
            checks["manual_editor_opened"]=true;
            auto button=[&](const QString &text) -> QPushButton* {
                for (auto *b:editor->findChildren<QPushButton*>()) if (b->text()==text) return b;
                return nullptr;
            };
            auto *canvas=editor->canvas; auto *viewport=canvas->viewport(); canvas->fit();
            button(QStringLiteral("新增框（拖动绘制）"))->click();
            const QPoint begin=canvas->mapFromScene(QPointF(probe.photo.width()*.3,probe.photo.height()*.3));
            const QPoint end=canvas->mapFromScene(QPointF(probe.photo.width()*.5,probe.photo.height()*.5));
            QTest::mousePress(viewport,Qt::LeftButton,Qt::NoModifier,begin);
            QTest::mouseMove(viewport,end); QTest::mouseRelease(viewport,Qt::LeftButton,Qt::NoModifier,end);
            checks["manual_draw_box"]=canvas->boxes().size()==1;
            if (canvas->boxes().size()!=1) { editor->reject(); return; }
            const double priorX=canvas->boxes()[0].x;
            const QPoint center=canvas->mapFromScene(canvas->boxRect(0).center()), moved=center+QPoint(30,20);
            QTest::mousePress(viewport,Qt::LeftButton,Qt::NoModifier,center);
            QTest::mouseMove(viewport,moved); QTest::mouseRelease(viewport,Qt::LeftButton,Qt::NoModifier,moved);
            checks["manual_move_box"]=canvas->boxes()[0].x>priorX;
            const double priorWidth=canvas->boxes()[0].w;
            const QPoint corner=canvas->mapFromScene(canvas->boxRect(0).bottomRight()), resized=corner+QPoint(24,18);
            QTest::mousePress(viewport,Qt::LeftButton,Qt::NoModifier,corner);
            QTest::mouseMove(viewport,resized); QTest::mouseRelease(viewport,Qt::LeftButton,Qt::NoModifier,resized);
            checks["manual_resize_box"]=canvas->boxes()[0].w>priorWidth;
            editor->findChild<QSpinBox*>()->setValue(2);
            checks["manual_edit_class"]=canvas->boxes()[0].classId==2;
            button(QStringLiteral("删除选中框"))->click();
            checks["manual_delete_box"]=canvas->boxes().isEmpty();
            editor->reject();
        });
        probe.editLabelButton->click();
        checks["manual_cancel_preserves_label"]=!QFileInfo::exists(fixtureLabel) && !probe.store.isDirty();
        QTimer::singleShot(0,&probe,[&] {
            auto *editor=dynamic_cast<LabelEditor*>(QApplication::activeModalWidget());
            if (!editor) return;
            editor->canvas->resetBoxes({{0,.5,.5,.1,.1}});
            editor->grab().save(QDir(output).filePath("manual-label-editor.png"));
            editor->findChild<QDialogButtonBox*>()->button(QDialogButtonBox::Save)->click();
        });
        probe.editLabelButton->click();
        checks["manual_save_label_pending"]=review::readLabels(fixtureLabel).boxes.size()==1
            && probe.store.value(0,"label_review_required")=="1" && !probe.store.isDirty();
        probe.setGalleryMode(true); QApplication::processEvents();
        checks["gallery_refreshes_after_manual_box_edit"] = probe.tiles->count()==1
            && probe.tiles->item(0)->text().contains(QStringLiteral("1框"))
            && probe.store.value(0,"label_review_required")=="1";
        probe.setGalleryMode(false);
        probe.activateWindow(); QTest::qWait(40);
        probe.search->setFocus(); QTest::keyClicks(probe.search,"a"); QTest::qWait(180);
        checks["approval_shortcut_disabled_while_typing"]=probe.store.value(0,"label_review_required")=="1";
        probe.search->clear(); QTest::qWait(180); probe.view->setFocus();
        QApplication::processEvents();
        QTest::keyClick(probe.view,Qt::Key_A);
        checks["approval_shortcut_saves"]=probe.store.value(0,"label_review_required")=="0"
            && probe.store.value(0,"annotation_status")=="reviewed_annotation" && !probe.store.isDirty();
#endif
        probe.goTo(0);
        const QByteArray beforeUncertain=review::readLabels(fixtureLabel).sourceHash;
        probe.uncertainReason->setCurrentIndex(probe.uncertainReason->findData("temporal_only"));
        if (!probe.markCurrentUncertain(false)) { error=probe.lastError; return false; }
        checks["uncertain_saved_and_protected"] = probe.store.isUncertain(0)
            && !probe.flags[3]->isEnabled() && !probe.approveLabelButton->isEnabled() && !probe.editLabelButton->isEnabled()
            && probe.store.value(0,"No Ball")=="0" && !probe.store.isDirty()
            && review::readLabels(fixtureLabel).sourceHash==beforeUncertain;
        probe.sceneFilter->setCurrentIndex(9);
        checks["uncertain_filter"] = probe.visible.size()==1 && probe.current==0;
        probe.grab().save(QDir(output).filePath("uncertain.png"));
        QTemporaryDir exportRoot;
        if (!probe.store.exportDataset(exportRoot.filePath("snapshot"),error)) return false;
        checks["uncertain_export_excluded"] = QDir(exportRoot.filePath("snapshot/images/"+split)).entryList(QDir::Files).isEmpty()
            && QFileInfo::exists(exportRoot.filePath("snapshot/uncertain/temporal_only/"+split+"/images/"+name));
        if (!probe.loadDataset(fixture.path(),error)) return false;
        checks["uncertain_survives_reload"] = probe.store.isUncertain(0) && !probe.approveLabelButton->isEnabled();
        if (!probe.requireCurrentCorrection(false)) { error=probe.lastError; return false; }
        checks["uncertain_reopen_pending"] = !probe.store.isUncertain(0)
            && probe.store.value(0,"label_review_required")=="1" && probe.editLabelButton->isEnabled();
        checks["fixture_dirty_after_save"] = probe.store.isDirty();
        bool ok = checks["real_metadata_not_edited"].toBool() && checks["checkbox_changes_metadata_state"].toBool()
            && checks["ui_save_roundtrip"].toBool() && checks["annotation_status_preserved"].toBool() && checks["label_readonly"].toBool()
            && checks["saved_filter_refresh"].toBool() && checks["overlay_toggle_preserves_zoom"].toBool() && !probe.store.isDirty()
            && checks["pending_label_not_automatically_approved"].toBool() && checks["pending_label_filter"].toBool()
            && checks["ui_stale_label_refused"].toBool() && checks["ui_explicit_label_approval_saved"].toBool()
            && checks["approved_label_leaves_pending_filter"].toBool() && checks["ui_label_correction_saved"].toBool()
            && checks["ui_empty_positive_label_refused"].toBool() && checks["ui_negative_label_approval_saved"].toBool()
            && checks["ui_missing_label_refused"].toBool() && checks["ui_missing_label_can_require_correction"].toBool();
#ifdef REVIEW_GUI_TESTING
        ok = ok && checks["search_typing_does_not_toggle_flags"].toBool() && checks["image_numeric_shortcut"].toBool();
        for (const auto &key : {"manual_editor_opened","manual_draw_box","manual_move_box","manual_resize_box",
                "manual_edit_class","manual_delete_box","manual_cancel_preserves_label","manual_save_label_pending",
                "approval_shortcut_disabled_while_typing","approval_shortcut_saves","gallery_refreshes_after_manual_box_edit"}) ok = ok && checks[key].toBool();
#endif
        for (const auto &key : {"uncertain_saved_and_protected","uncertain_filter","uncertain_export_excluded",
                "uncertain_survives_reload","uncertain_reopen_pending","batch_list_order_and_count",
                "batch_navigation_stays_in_scope","batch_filters_keep_scope","batch_save_preserves_full_metadata",
                "gallery_keeps_batch_scope_and_order","gallery_click_opens_selected_image_without_approval",
                "gallery_return_refreshes_edited_metadata","gallery_shortcuts_do_not_approve_hidden_image",
                "gallery_first_page_has_50_images","gallery_last_page_has_remaining_3",
                "gallery_filter_keeps_original_image_number","gallery_return_keeps_selection_visible",
                "gallery_zero_flags_are_blank","gallery_selected_flags_use_chinese_only"}) ok = ok && checks[key].toBool();
        if (scopeRows_.size()>50) for (const auto &key : {"real_gallery_first_page_can_advance",
                "real_gallery_second_page_has_stable_group_numbers","real_gallery_click_opens_single_image","real_gallery_click_return_keeps_page_and_selection",
                "real_gallery_last_page_correct_remainder","real_gallery_last_page_can_go_back",
                "gallery_page_out_of_range_refused","real_gallery_browsing_preserves_all_reviews"}) ok = ok && checks[key].toBool();
        checks["success"] = ok; QFile report(QDir(output).filePath("smoke.json"));
        if (!report.open(QIODevice::WriteOnly)) { error="Cannot write report"; return false; }
        report.write(QJsonDocument(checks).toJson(QJsonDocument::Indented)); return ok;
    }
protected:
    void closeEvent(QCloseEvent *event) override { if (permitLeaving()) event->accept(); else event->ignore(); }
private:
    QStackedWidget *content; QWidget *gallery; QListWidget *tiles;
    QPushButton *galleryButton, *galleryPrevious, *galleryNext; QLabel *galleryCount; int galleryPage=0;
    QLineEdit *datasetPath, *search; QComboBox *splitFilter, *sceneFilter, *uncertainReason; QTableWidget *table;
    QLabel *count, *caption, *status, *details, *labelReviewStatus; QCheckBox *flags[4], *reviewNeeded, *drawBoxes;
    QPlainTextEdit *reviewNote;
    QPlainTextEdit *labelText; QPushButton *exportButton, *uncertainButton, *saveButton, *confirmButton, *approveLabelButton, *correctionButton, *editLabelButton, *openLabelButton, *reloadLabelButton; ImageView *view;
    QVector<int> visible, scopeRows_; QString imageListPath_;
    QVector<QShortcut*> sensitiveShortcuts; QTimer searchTimer; int current=-1; bool loading=false;
    QPixmap photo; review::LabelData labelData; QString lastError;
    void updateSensitiveShortcuts() {
        QWidget *focus=QApplication::focusWidget();
        const bool typing=qobject_cast<QLineEdit*>(focus) || qobject_cast<QPlainTextEdit*>(focus) || qobject_cast<QTextEdit*>(focus);
        for (auto *shortcut : sensitiveShortcuts) shortcut->setEnabled(!typing && !galleryMode());
    }
    void fillTile(QListWidgetItem *item, int row) {
        const int position=scopeRows_.indexOf(row);
        const QPixmap source(store.imagePath(row));
        const review::LabelData labels=review::readLabels(store.labelPath(row));
        QPixmap thumbnail(250,142); thumbnail.fill(QColor("#17202b"));
        QPainter painter(&thumbnail); painter.setRenderHint(QPainter::SmoothPixmapTransform);
        if (!source.isNull()) {
            const QSize size=source.size().scaled(thumbnail.size(),Qt::KeepAspectRatio);
            const QRect target((thumbnail.width()-size.width())/2,(thumbnail.height()-size.height())/2,size.width(),size.height());
            painter.drawPixmap(target,source);
            painter.setRenderHint(QPainter::Antialiasing,false);
            const int preserved=store.value(row,"preserved_box_count").toInt();
            for (int index=0;index<labels.boxes.size();++index) {
                const auto &box=labels.boxes[index];
                painter.setPen(QPen(QColor(pendingLabelReview(row) && index>=preserved ? "#ffad42" : "#50edab"),1));
                painter.drawRect(QRectF(target.x()+(box.x-box.w/2)*target.width(),target.y()+(box.y-box.h/2)*target.height(),box.w*target.width(),box.h*target.height()));
            }
        } else { painter.setPen(Qt::white); painter.drawText(thumbnail.rect(),Qt::AlignCenter,QStringLiteral("图片无法解码")); }
        painter.end();
        const QString scenes=sceneSummary(row);
        QString state=store.value(row,"annotation_status")=="reviewed_excluded" && !pendingLabelReview(row) && store.value(row,"scene_review_required")=="0" ? QStringLiteral("已审核 · 暂不训练")
            : store.isUncertain(row) ? QStringLiteral("不确定")
            : pendingLabelReview(row) || store.value(row,"scene_review_required")=="1" ? QStringLiteral("待审核") : QStringLiteral("已审核");
        if (!labels.exists || !labels.errors.isEmpty()) state+=QStringLiteral(" · label异常");
        if (store.rowDirty(row)) state+=QStringLiteral(" · 未保存");
        item->setData(Qt::UserRole,row); item->setIcon(QIcon(thumbnail));
        const QString number=QStringLiteral("第%1组 · %2号").arg(position/50+1).arg(position%50+1,2,10,QChar('0'));
        item->setText(QStringLiteral("%1\n%2\n%3\n%4框 · %5").arg(number,store.value(row,QStringLiteral("图片")),scenes)
            .arg(labels.boxes.size()).arg(state));
        item->setToolTip(QStringLiteral("%1\n%2\n%3\n点击进入单图，修改框或分类；按 G 返回平铺。")
            .arg(store.value(row,QStringLiteral("图片")),sceneSummary(row),store.value(row,"label_review_note")));
        item->setTextAlignment(Qt::AlignHCenter); item->setSizeHint(QSize(268,238));
    }
    void rebuildGallery() {
        galleryPage=qBound(0,galleryPage,qMax(0,(visible.size()-1)/50));
        QSignalBlocker block(tiles); tiles->clear();
        const int start=galleryPage*50, end=qMin(start+50,visible.size());
        for (int position=start;position<end;++position) {
            auto *item=new QListWidgetItem(tiles); fillTile(item,visible[position]);
            if (visible[position]==current) tiles->setCurrentItem(item);
        }
        galleryCount->setText(visible.isEmpty() ? QStringLiteral("没有匹配图片")
            : QStringLiteral("第 %1 / %2 页 · 第 %3–%4 张 / 共 %5 张 · 每页最多50张")
                .arg(galleryPage+1).arg((visible.size()+49)/50).arg(start+1).arg(end).arg(visible.size()));
        galleryPrevious->setEnabled(galleryPage>0); galleryNext->setEnabled(end<visible.size());
    }
    QString sceneSummary(int row) const {
        QStringList result;
        for (int i=0;i<4;++i) if (store.value(row,kFlags[i])=="1") result<<kSceneNames[i];
        return result.join(QStringLiteral(" · "));
    }
    bool matches(int row) const { if (splitFilter->currentIndex()>0 && store.value(row,"split")!=splitFilter->currentText()) return false;
        if (!store.value(row,QStringLiteral("图片")).contains(search->text(),Qt::CaseInsensitive)) return false;
        int filter=sceneFilter->currentIndex(); if (filter>=1 && filter<=4) return store.value(row,kFlags[filter-1])=="1";
        if (filter==5) { for (const auto &flag:kFlags) if (store.value(row,flag)=="1") return false; }
        if (filter==6) return store.value(row,"scene_review_required")=="1";
        if (filter==7) return !QFileInfo::exists(store.labelPath(row));
        if (filter==8) return pendingLabelReview(row); if (filter==9) return store.isUncertain(row); return true; }
    void rebuild(int preferredPosition=0) { int previous=current; QSignalBlocker block(table); table->setRowCount(0); visible.clear();
        for (int row : scopeRows_) if (matches(row)) { int pos=visible.size(); visible<<row; table->insertRow(pos);
            for (int col=0;col<3;++col) table->setItem(pos,col,new QTableWidgetItem); refreshRow(row); }
        count->setText(imageListPath_.isEmpty()
            ? QStringLiteral("显示 %1 / %2 张").arg(visible.size()).arg(scopeRows_.size())
            : QStringLiteral("批次 %1\n显示 %2 / 本批 %3 张（全库 %4 张）")
                .arg(QFileInfo(imageListPath_).fileName()).arg(visible.size()).arg(scopeRows_.size()).arg(store.rows.size()));
        int pos=visible.indexOf(previous); if (pos<0 && !visible.isEmpty()) pos=qBound(0,preferredPosition,visible.size()-1);
        table->setCurrentCell(pos,0); block.unblock();
        if (pos>=0) selectRow(visible[pos]); else { current=-1; photo={}; labelData={}; view->showImage(photo,labelData,false);
            caption->setText(QStringLiteral("筛选结果为空")); labelText->clear(); reviewNote->clear(); details->clear(); status->clear(); labelReviewStatus->clear(); updateDirty(); }
        rebuildGallery();
    }
    void refreshRow(int row) { int pos=visible.indexOf(row); if (pos<0) return;
        table->item(pos,0)->setText((store.rowDirty(row)?"* ":"")+store.value(row,QStringLiteral("图片")));
        table->item(pos,1)->setText(store.value(row,"split")); table->item(pos,2)->setText(sceneSummary(row));
        if (galleryMode()) for (int index=0;index<tiles->count();++index) {
            auto *item=tiles->item(index); if (item->data(Qt::UserRole).toInt()==row) { fillTile(item,row); break; }
        }
    }
    void selectRow(int row) { if (row<0 || row>=store.rows.size()) return; current=row; loading=true;
        for (int i=0;i<4;++i) flags[i]->setChecked(store.value(row,kFlags[i])=="1"); reviewNeeded->setChecked(store.value(row,"scene_review_required")=="1"); loading=false;
        const int reasonIndex = uncertainReason->findData(store.value(row,"annotation_status"));
        uncertainReason->setCurrentIndex(qMax(0,reasonIndex));
        photo=QPixmap(store.imagePath(row)); labelData=review::readLabels(store.labelPath(row)); drawCurrent();
        labelText->setPlainText(labelData.raw);
        reviewNote->setPlainText(store.value(row,"label_review_note"));
        QString labelState;
        if (!labelData.exists) labelState=QStringLiteral("缺少 label：图片未标注（不是空负样本）");
        else if (!labelData.errors.isEmpty()) labelState=QStringLiteral("label 有错误：\n")+labelData.errors.join('\n');
        else if (labelData.boxes.isEmpty()) labelState=QStringLiteral("label 为空：0 个目标框");
        else labelState=QStringLiteral("label：%1 个有效框%2").arg(labelData.boxes.size())
            .arg(pendingLabelReview(row) ? QStringLiteral("（待人工审核）") : QString());
        status->setText(labelState); status->setStyleSheet(!labelData.exists || !labelData.errors.isEmpty() || pendingLabelReview(row) ? "color:#b94f24;font-weight:600" : "color:#168153;font-weight:600");
        labelReviewStatus->setText(store.value(row,"annotation_status")=="reviewed_excluded"
            ? QStringLiteral("已人工审核 · 暂不训练\n原框和判断原因保留；导出时单独归档。")
            : store.isUncertain(row)
            ? QStringLiteral("uncertain：导出时排除训练、验证和标准测试。\n原框仅供参考；复核当前帧后才能恢复审核。")
            : pendingLabelReview(row)
            ? QStringLiteral("待label人工审核\n候选框不能视为已确认标注。保留框 %1；自动候选 %2。")
                .arg(store.value(row,"preserved_box_count"),store.value(row,"auto_box_count"))
            : store.headers.contains("label_review_required") ? QStringLiteral("label审核标记：已通过")
                                                             : QStringLiteral("此CSV未提供label审核列"));
        labelReviewStatus->setStyleSheet(pendingLabelReview(row) ? "background:#fff1d8;color:#9b5200;padding:8px;font-weight:700" : "color:#168153;font-weight:600");
        const auto annotation=store.value(row,"annotation_status");
        const QMap<QString,QString> statuses{{"negative_confirmed",QStringLiteral("确认无球")},{"needs_bbox_annotation",QStringLiteral("待目标框标注")},
            {"auto_label_needs_review",QStringLiteral("自动预标注待人工审核")},{"needs_manual_bbox_annotation",QStringLiteral("待人工补充或修正目标框")},
            {"reviewed_annotation",QStringLiteral("目标框已人工审核")},{"reviewed_excluded",QStringLiteral("已人工审核，暂不训练")},{"needs_visibility_review",QStringLiteral("待可见性复核")},{"provided_annotation",QStringLiteral("已有目标框标注")},{"provided_annotation_needs_review",QStringLiteral("已有标注待复核")}};
        details->setText(QStringLiteral("标注状态：%1\n\n图片：%2\n\nlabel：%3").arg(statuses.value(annotation,annotation),store.imagePath(row),store.labelPath(row)));
        updateDirty(); }
    void drawCurrent(bool preserveView=false) { view->showImage(photo,labelData,drawBoxes->isChecked(),preserveView, pendingLabelReview(current), store.value(current,"preserved_box_count").toInt()); if (current>=0)
        caption->setText(QStringLiteral("%1  ·  %2  ·  %3×%4  ·  当前 %5/%6").arg(store.value(current,QStringLiteral("图片")),store.value(current,"split"))
            .arg(photo.width()).arg(photo.height()).arg(visible.indexOf(current)+1).arg(visible.size())); }
    void updateDirty() { const bool ready=current>=0; for (auto *flag:flags) flag->setEnabled(ready); reviewNeeded->setEnabled(ready && store.headers.contains("scene_review_required")); confirmButton->setEnabled(ready);
        const bool labelReviewReady=ready && store.headers.contains("label_review_required");
        exportButton->setEnabled(!store.root.isEmpty());
        uncertainButton->setEnabled(labelReviewReady); uncertainReason->setEnabled(labelReviewReady);
        flags[3]->setEnabled(ready && !store.isUncertain(current));
        approveLabelButton->setEnabled(labelReviewReady && !store.isUncertain(current));
        correctionButton->setText(store.isUncertain(current) ? QStringLiteral("重新复核") : QStringLiteral("label需修正"));
        correctionButton->setEnabled(labelReviewReady);
        editLabelButton->setEnabled(labelReviewReady && !store.isUncertain(current) && !photo.isNull());
        openLabelButton->setEnabled(ready && labelData.exists);
        reloadLabelButton->setEnabled(ready);
        saveButton->setEnabled(store.isDirty());
        QString title=QStringLiteral("足球数据集审核");
        if (!imageListPath_.isEmpty()) title+=QStringLiteral(" · %1").arg(QFileInfo(imageListPath_).fileName());
        if (store.isDirty()) title+=QStringLiteral(" · 未保存 %1 张").arg(store.dirtyCount());
        setWindowTitle(title); }
    void navigate(int step) { int pos=visible.indexOf(current); if (pos<0 || visible.isEmpty()) return;
        pos=qBound(0,pos+step,visible.size()-1); table->setCurrentCell(pos,0); view->setFocus(); }
    void confirmCurrent() { if (current<0) return; const int old=current, pos=visible.indexOf(current); reviewNeeded->setChecked(false);
        if (!saveChanges()) return; rebuild(pos); if (current==old) navigate(1); view->setFocus(); }
    bool pendingLabelReview(int row) const {
        const QString annotation=store.value(row,"annotation_status");
        return store.isUncertain(row) || store.value(row,"label_review_required")=="1" || annotation=="auto_label_needs_review"
            || annotation=="needs_manual_bbox_annotation";
    }
    void editCurrentLabel() {
        if (!editLabelButton->isEnabled()) return;
        const int row=current, position=visible.indexOf(current);
        const review::LabelData displayed=labelData;
        LabelEditor editor(photo,displayed,[this,row,displayed](const QVector<review::Box> &boxes, QString &error) {
            return store.saveLabelBoxes(row,displayed,boxes,error);
        },this);
        if (editor.exec()==QDialog::Accepted) {
            rebuild(position); updateDirty();
            statusBar()->showMessage(QStringLiteral("label已保存，原文件已备份；请核对后按 A 审核通过"),6000);
        } else { refreshRow(row); updateDirty(); }
        view->setFocus();
    }
    bool approveCurrentLabel(bool dialogs=true) {
        if (current<0) return false;
        const int row=current, position=visible.indexOf(current);
        QString error;
        if (!store.approveAnnotation(row,labelData.sourceHash,error)) {
            // Refresh the view; a changed file always requires another explicit approval click.
            selectRow(row); lastError=error;
            if (dialogs) QMessageBox::warning(this,QStringLiteral("label未通过审核"),error);
            return false;
        }
        if (!saveChanges(dialogs)) return false;
        rebuild(position); statusBar()->showMessage(QStringLiteral("当前label已人工审核通过并保存"),6000);
        return true;
    }
    bool markCurrentUncertain(bool dialogs=true) {
        if (current<0) return false;
        QString error;
        if (!store.markUncertain(current,uncertainReason->currentData().toString(),error)) {
            lastError=error;
            if (dialogs) QMessageBox::warning(this,QStringLiteral("无法标记不确定"),error);
            return false;
        }
        if (!saveChanges(dialogs)) { selectRow(current); return false; }
        statusBar()->showMessage(QStringLiteral("不确定状态已保存；导出时独立保留，不参与普通训练和标准评测"),6000);
        return true;
    }
    bool requireCurrentCorrection(bool dialogs=true) {
        if (current<0) return false;
        QString error;
        if (!store.requireAnnotationCorrection(current,error)) {
            lastError=error;
            if (dialogs) QMessageBox::warning(this,QStringLiteral("无法标记需修正"),error);
            return false;
        }
        if (!saveChanges(dialogs)) return false;
        statusBar()->showMessage(QStringLiteral("当前label已标记为待人工修正并保存"),6000);
        return true;
    }
    bool permitLeaving() { if (!store.isDirty()) return true;
        auto reply=QMessageBox::question(this,QStringLiteral("有未保存的审核"),QStringLiteral("保存所有审核修改后继续？"),QMessageBox::Save|QMessageBox::Discard|QMessageBox::Cancel,QMessageBox::Save);
        if (reply==QMessageBox::Save) return saveChanges(); return reply==QMessageBox::Discard; }
};

int main(int argc, char **argv) {
    QApplication app(argc,argv); QApplication::setApplicationName("football-dataset-reviewer"); QApplication::setApplicationVersion("1.4");
    QCommandLineParser parser; parser.setApplicationDescription(QStringLiteral("核对YOLO候选框，人工审核label与四项困难场景")); parser.addHelpOption();
    QCommandLineOption dataset({"d","dataset"},QStringLiteral("数据集根目录"),"directory"); QCommandLineOption smoke("smoke",QStringLiteral("用真实数据只读预览并在临时副本测试保存，输出报告"),"directory");
    QCommandLineOption imageList("image-list",QStringLiteral("批次图片名单：UTF-8，每行一个 metadata.csv 中的完整图片名"),"file");
    QCommandLineOption gallery("gallery",QStringLiteral("以每页最多50张的平铺网格启动，点击图片进入修改"));
    QCommandLineOption galleryPage("gallery-page",QStringLiteral("平铺启动页，1-based；须与 --gallery 一起使用"),"number");
    parser.addOption(dataset); parser.addOption(smoke); parser.addOption(imageList); parser.addOption(gallery); parser.addOption(galleryPage); parser.addPositionalArgument("dataset",QStringLiteral("可选数据集根目录")); parser.process(app);
    if (parser.isSet(imageList) && parser.value(imageList).isEmpty()) { qCritical().noquote()<<QStringLiteral("--image-list 需要非空文件路径。"); return 2; }
    int initialGalleryPage=1;
    if (parser.isSet(galleryPage)) {
        bool valid=false;
        const QString value=parser.value(galleryPage);
        initialGalleryPage=value.toInt(&valid);
        if (!parser.isSet(gallery)) { qCritical().noquote()<<QStringLiteral("--gallery-page 必须与 --gallery 一起使用。"); return 2; }
        if (!valid || initialGalleryPage<1 || !QRegularExpression(QStringLiteral("^[0-9]+$")).match(value).hasMatch()) {
            qCritical().noquote()<<QStringLiteral("--gallery-page 需要大于 0 的整数页码。"); return 2;
        }
    }
    QString root=parser.value(dataset); if (root.isEmpty() && !parser.positionalArguments().isEmpty()) root=parser.positionalArguments().first();
    if (root.isEmpty()) { for (const auto &p:QStringList{QDir::homePath()+"/workspace/datasets",QDir::homePath()+"/workspace/datasets/football_dataset",QDir::homePath()+"/workspace/dataset/football_dataset"})
        if (QFileInfo::exists(p+"/metadata.csv")) { root=p; break; } }
    ReviewWindow window; QString error;
    if (root.isEmpty() && parser.isSet(imageList)) { qCritical().noquote()<<QStringLiteral("使用 --image-list 时须先指定或找到数据集。"); return 2; }
    if (!root.isEmpty() && !window.loadDataset(root,error,parser.value(imageList))) { if (parser.isSet(smoke) || parser.isSet(imageList)) { qCritical().noquote()<<error; return 2; }
        QMessageBox::warning(&window,QStringLiteral("无法打开数据集"),error); }
    if (parser.isSet(galleryPage)) { if (!window.openGalleryPage(initialGalleryPage,error)) { qCritical().noquote()<<error; return 2; } }
    else window.setGalleryMode(parser.isSet(gallery));
    window.show();
    if (parser.isSet(smoke)) { QApplication::processEvents(); if (window.store.rows.isEmpty()) return 2;
        bool ok=window.smoke(parser.value(smoke),error); if (!ok) qCritical().noquote()<<error; return ok?0:3; }
    return app.exec();
}
