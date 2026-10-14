#pragma once

#include "dataset_store.h"
#include <QtWidgets>
#include <cmath>
#include <functional>
#include <limits>

// Edits stay in this canvas until the dialog's explicit save action.
class LabelCanvas : public QGraphicsView {
public:
    LabelCanvas(const QPixmap &image, const QVector<review::Box> &boxes, QWidget *parent=nullptr)
        : QGraphicsView(parent), imageSize(image.size()), boxes_(boxes) {
        setScene(&canvas); canvas.addPixmap(image); canvas.setSceneRect(QRectF(QPointF(), image.size()));
        setBackgroundBrush(QColor("#161c26")); setRenderHints(QPainter::Antialiasing | QPainter::SmoothPixmapTransform);
        setTransformationAnchor(AnchorUnderMouse); setFocusPolicy(Qt::StrongFocus); redraw();
    }
    std::function<void()> changed;
    QVector<review::Box> boxes() const { return boxes_; }
    int selected() const { return selected_; }
    void setAdding(bool value) { adding=value; setCursor(value ? Qt::CrossCursor : Qt::ArrowCursor); }
    void fit() { autoFit=true; fitInView(canvas.sceneRect(), Qt::KeepAspectRatio); redraw(); }
    void resetBoxes(const QVector<review::Box> &boxes) { boxes_=boxes; selected_=-1; redraw(); notify(); }
    void deleteSelected() {
        if (selected_<0) return;
        boxes_.removeAt(selected_); selected_=-1; redraw(); notify();
    }
    void updateSelected(const review::Box &box) {
        if (selected_<0) return;
        boxes_[selected_]=box; redraw(); notify();
    }
    QRectF boxRect(int index) const {
        const auto &box=boxes_[index];
        return {(box.x-box.w/2)*imageSize.width(), (box.y-box.h/2)*imageSize.height(),
                box.w*imageSize.width(), box.h*imageSize.height()};
    }
protected:
    void resizeEvent(QResizeEvent *event) override { QGraphicsView::resizeEvent(event); if (autoFit) fit(); }
    void wheelEvent(QWheelEvent *event) override {
        autoFit=false; const double factor=event->angleDelta().y()>0 ? 1.2 : 1/1.2;
        const double zoom=transform().m11()*factor;
        if (zoom>=.03 && zoom<=80) { scale(factor,factor); redraw(); } event->accept();
    }
    void mousePressEvent(QMouseEvent *event) override {
        if (event->button()==Qt::RightButton || event->button()==Qt::MiddleButton) {
            panning=true; panStart=event->position().toPoint(); setCursor(Qt::ClosedHandCursor); event->accept(); return;
        }
        if (event->button()!=Qt::LeftButton) { QGraphicsView::mousePressEvent(event); return; }
        setFocus(); start=clamp(mapToScene(event->position().toPoint())); resizing=false; dragging=false;
        if (adding) { drawing=true; draft=QRectF(start,start); redraw(); event->accept(); return; }
        // Selected corner handles take precedence over overlapping boxes.
        if (selected_>=0) {
            const QRectF rect=boxRect(selected_);
            const QList<QPointF> corners{rect.topLeft(),rect.topRight(),rect.bottomRight(),rect.bottomLeft()};
            for (int i=0; i<corners.size(); ++i) {
                const double tolerance=qMin(10.,qMin(rect.width(),rect.height())*transform().m11()*.35);
                if (QLineF(QPointF(mapFromScene(corners[i])),event->position()).length()<=qMax(2.,tolerance)) {
                    resizing=true; anchor=corners[(i+2)%4]; break;
                }
            }
        }
        if (!resizing) {
            selected_=-1;
            const QPointF point=mapToScene(event->position().toPoint());
            const double pad=5/transform().m11();
            for (int i=boxes_.size()-1; i>=0; --i)
                if (boxRect(i).adjusted(-pad,-pad,pad,pad).contains(point)) { selected_=i; break; }
            if (selected_>=0) { dragging=true; originalRect=boxRect(selected_); }
        }
        redraw(); notify(); event->accept();
    }
    void mouseMoveEvent(QMouseEvent *event) override {
        if (panning) {
            const QPoint now=event->position().toPoint(), delta=now-panStart; panStart=now; autoFit=false;
            horizontalScrollBar()->setValue(horizontalScrollBar()->value()-delta.x());
            verticalScrollBar()->setValue(verticalScrollBar()->value()-delta.y()); event->accept(); return;
        }
        const QPointF point=clamp(mapToScene(event->position().toPoint()));
        if (drawing) { draft=QRectF(start,point).normalized(); redraw(); }
        else if (resizing) { const QRectF rect=QRectF(anchor,point).normalized(); if (rect.width()>0 && rect.height()>0) setRect(rect); }
        else if (dragging) {
            QRectF rect=originalRect.translated(point-start);
            // Translation preserves size, including existing edge-straddling boxes.
            rect.moveLeft(qBound(-rect.width()/2,rect.left(),imageSize.width()-rect.width()/2));
            rect.moveTop(qBound(-rect.height()/2,rect.top(),imageSize.height()-rect.height()/2));
            setRect(rect);
        } else { QGraphicsView::mouseMoveEvent(event); return; }
        event->accept();
    }
    void mouseReleaseEvent(QMouseEvent *event) override {
        if (panning && (event->button()==Qt::RightButton || event->button()==Qt::MiddleButton)) {
            panning=false; setCursor(adding ? Qt::CrossCursor : Qt::ArrowCursor); event->accept(); return;
        }
        if (event->button()!=Qt::LeftButton) { QGraphicsView::mouseReleaseEvent(event); return; }
        if (drawing) {
            draft=QRectF(start,clamp(mapToScene(event->position().toPoint()))).normalized();
            if (draft.width()*transform().m11()>=3 && draft.height()*transform().m22()>=3) {
                boxes_.append(fromRect(draft,0)); selected_=boxes_.size()-1;
                setAdding(false);
            }
        }
        drawing=dragging=resizing=false; redraw(); notify(); event->accept();
    }
private:
    QGraphicsScene canvas; QSize imageSize; QVector<review::Box> boxes_; QList<QGraphicsItem*> overlays;
    int selected_=-1; bool adding=false, drawing=false, dragging=false, resizing=false, panning=false, autoFit=true;
    QPointF start, anchor; QPoint panStart; QRectF draft, originalRect;
    QPointF clamp(QPointF point) const {
        return {qBound(0.,point.x(),double(imageSize.width())),qBound(0.,point.y(),double(imageSize.height()))};
    }
    review::Box fromRect(const QRectF &rect, int classId) const {
        return {classId, rect.center().x()/imageSize.width(), rect.center().y()/imageSize.height(),
                rect.width()/imageSize.width(), rect.height()/imageSize.height()};
    }
    void setRect(const QRectF &rect) { boxes_[selected_]=fromRect(rect,boxes_[selected_].classId); redraw(); notify(); }
    void notify() { if (changed) changed(); }
    void redraw() {
        for (auto *item:overlays) delete item; overlays.clear();
        for (int i=0; i<boxes_.size(); ++i) {
            const QRectF rect=boxRect(i); const QColor color(i==selected_ ? "#60caff" : "#ffad42");
            QPen pen(color,2); pen.setCosmetic(true); overlays << canvas.addRect(rect,pen);
            auto *text=canvas.addSimpleText(QString("%1 · class %2").arg(i+1).arg(boxes_[i].classId));
            text->setBrush(color); text->setFlag(QGraphicsItem::ItemIgnoresTransformations); text->setPos(rect.topLeft()); overlays << text;
            if (i==selected_) {
                const double size=8/transform().m11();
                for (const auto &corner : {rect.topLeft(),rect.topRight(),rect.bottomLeft(),rect.bottomRight()})
                    overlays << canvas.addRect(QRectF(corner-QPointF(size/2,size/2),QSizeF(size,size)),pen,color);
            }
        }
        if (drawing) { QPen pen(QColor("#60caff"),2,Qt::DashLine); pen.setCosmetic(true); overlays << canvas.addRect(draft,pen); }
    }
};

class LabelEditor : public QDialog {
public:
    LabelEditor(const QPixmap &image, const review::LabelData &labels,
                std::function<bool(const QVector<review::Box> &, QString &)> save, QWidget *parent=nullptr)
        : QDialog(parent) {
        setWindowTitle(QStringLiteral("手工修改 label")); resize(1080,800);
        auto *layout=new QVBoxLayout(this); auto *toolbar=new QHBoxLayout; layout->addLayout(toolbar);
        add=new QPushButton(QStringLiteral("新增框（拖动绘制）")); add->setCheckable(true); toolbar->addWidget(add);
        remove=new QPushButton(QStringLiteral("删除选中框")); toolbar->addWidget(remove);
        auto *reset=new QPushButton(QStringLiteral("还原本次修改")); toolbar->addWidget(reset);
        auto *fit=new QPushButton(QStringLiteral("适应窗口")); toolbar->addWidget(fit); toolbar->addStretch();
        info=new QLabel; toolbar->addWidget(info);
        auto *help=new QLabel(QStringLiteral("点击框选中，拖动框移动，拖动四角调整大小；新增框后可修改类别。滚轮缩放，右键/中键拖动平移。\n保存会备份原 label，并将其标记为待审核；核对后在主窗口按 A 审核通过。"));
        help->setWordWrap(true); layout->addWidget(help);
        if (!labels.errors.isEmpty()) {
            auto *warning=new QLabel(QStringLiteral("原 label 有格式错误；本次保存将用画面中的有效框替换全部内容，请补齐遗漏的框。\n")+labels.errors.join('\n'));
            warning->setWordWrap(true); warning->setStyleSheet("color:#b94f24"); layout->addWidget(warning);
        }
        canvas=new LabelCanvas(image,labels.boxes,this); layout->addWidget(canvas,1);
        auto *fields=new QHBoxLayout; layout->addLayout(fields);
        fields->addWidget(new QLabel(QStringLiteral("选中框类别"))); classId=new QSpinBox; classId->setRange(0,std::numeric_limits<int>::max()); fields->addWidget(classId);
        const QStringList names{"x中心","y中心","宽","高"};
        for (int i=0; i<4; ++i) {
            fields->addWidget(new QLabel(names[i])); coordinates[i]=new QDoubleSpinBox;
            coordinates[i]->setDecimals(8); coordinates[i]->setRange(i<2 ? 0 : .00000001,1);
            coordinates[i]->setSingleStep(.001); coordinates[i]->setKeyboardTracking(false); fields->addWidget(coordinates[i]);
            connect(coordinates[i],qOverload<double>(&QDoubleSpinBox::valueChanged),this,[this,i](double value) {
                if (canvas->selected()<0) return; auto box=canvas->boxes()[canvas->selected()];
                if (i==0) box.x=value; else if (i==1) box.y=value; else if (i==2) box.w=value; else box.h=value;
                canvas->updateSelected(box);
            });
        }
        classId->setKeyboardTracking(false);
        connect(classId,qOverload<int>(&QSpinBox::valueChanged),this,[this](int value) {
            if (canvas->selected()<0) return; auto box=canvas->boxes()[canvas->selected()]; box.classId=value; canvas->updateSelected(box);
        });
        connect(add,&QPushButton::toggled,canvas,[this](bool value) { canvas->setAdding(value); });
        connect(remove,&QPushButton::clicked,canvas,[this] { canvas->deleteSelected(); });
        connect(reset,&QPushButton::clicked,canvas,[this,labels] { add->setChecked(false); canvas->resetBoxes(labels.boxes); });
        connect(fit,&QPushButton::clicked,canvas,[this] { canvas->fit(); });
        canvas->changed=[this] { syncFields(); };
        auto *buttons=new QDialogButtonBox(QDialogButtonBox::Save | QDialogButtonBox::Cancel);
        buttons->button(QDialogButtonBox::Save)->setText(QStringLiteral("保存 label 并待审核")); layout->addWidget(buttons);
        connect(buttons,&QDialogButtonBox::rejected,this,&QDialog::reject);
        connect(buttons,&QDialogButtonBox::accepted,this,[this,save] {
            // Commit a spinbox value still being typed before reading the canvas.
            classId->interpretText(); for (auto *coordinate:coordinates) coordinate->interpretText();
            QString error; if (!save(canvas->boxes(),error)) { QMessageBox::warning(this,QStringLiteral("label未保存"),error); return; }
            accept();
        });
        syncFields();
    }
    LabelCanvas *canvas;
private:
    QPushButton *add, *remove; QLabel *info; QSpinBox *classId; QDoubleSpinBox *coordinates[4];
    void syncFields() {
        const int selected=canvas->selected(); const bool ready=selected>=0;
        remove->setEnabled(ready); classId->setEnabled(ready); for (auto *coordinate:coordinates) coordinate->setEnabled(ready);
        info->setText(QStringLiteral("%1 个框 · %2").arg(canvas->boxes().size()).arg(ready ? QStringLiteral("选中 #%1").arg(selected+1) : QStringLiteral("未选中")));
        if (!ready) return;
        // A completed draw exits add mode.
        if (add->isChecked()) add->setChecked(false);
        const auto box=canvas->boxes()[selected]; QSignalBlocker blockClass(classId); classId->setValue(box.classId);
        const double values[]{box.x,box.y,box.w,box.h};
        for (int i=0; i<4; ++i) { QSignalBlocker block(coordinates[i]); coordinates[i]->setValue(values[i]); }
    }
};
