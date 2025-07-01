import sys
import os
from PyQt6.QtWidgets import (QApplication, QMainWindow, QVBoxLayout, QHBoxLayout, 
                             QWidget, QPushButton, QLabel, QProgressBar, QTextEdit, 
                             QFileDialog, QGroupBox, QComboBox, QSpinBox, QCheckBox,
                             QMessageBox, QGridLayout, QFrame, QSlider)
from PyQt6.QtCore import Qt, QThread, pyqtSignal, QTimer
from PyQt6.QtGui import QFont, QIcon, QPalette, QColor
import fitz  # PyMuPDF
from PIL import Image
import io
import tempfile
import shutil
import gc


class PDFCompressorThread(QThread):
    progress_updated = pyqtSignal(int)
    log_updated = pyqtSignal(str)
    finished_signal = pyqtSignal(bool, str)
    
    def __init__(self, input_files, output_folder, quality, dpi, remove_images, 
                 remove_annotations, compress_fonts, max_image_size, compression_level):
        super().__init__()
        self.input_files = input_files
        self.output_folder = output_folder
        self.quality = quality
        self.dpi = dpi
        self.remove_images = remove_images
        self.remove_annotations = remove_annotations
        self.compress_fonts = compress_fonts
        self.max_image_size = max_image_size
        self.compression_level = compression_level
        
    def run(self):
        try:
            total_files = len(self.input_files)
            for i, file_path in enumerate(self.input_files):
                self.log_updated.emit(f"İşleniyor: {os.path.basename(file_path)}")
                
                # Büyük dosyalar için özel işlem
                file_size = os.path.getsize(file_path)
                self.log_updated.emit(f"Dosya boyutu: {self.format_size(file_size)}")
                
                if file_size > 50 * 1024 * 1024:  # 50MB+
                    self.log_updated.emit("Büyük dosya tespit edildi, özel sıkıştırma uygulanıyor...")
                
                # PDF'yi yükle
                doc = fitz.open(file_path)
                self.log_updated.emit(f"Toplam sayfa sayısı: {len(doc)}")
                
                # Yeni PDF oluştur
                new_doc = fitz.open()
                
                # Her sayfayı işle
                total_pages = len(doc)
                for page_num in range(total_pages):
                    page = doc.load_page(page_num)
                    
                    # Büyük dosyalar için agresif sıkıştırma
                    if file_size > 30 * 1024 * 1024:  # 30MB+
                        # Sayfa boyutunu kontrol et ve gerekirse küçült
                        page_rect = page.rect
                        if page_rect.width > self.max_image_size or page_rect.height > self.max_image_size:
                            scale = min(self.max_image_size / page_rect.width, 
                                      self.max_image_size / page_rect.height)
                            mat = fitz.Matrix(scale * self.dpi/72, scale * self.dpi/72)
                        else:
                            mat = fitz.Matrix(self.dpi/72, self.dpi/72)
                    else:
                        mat = fitz.Matrix(self.dpi/72, self.dpi/72)
                    
                    # Görüntüleri işle
                    if not self.remove_images and self.quality < 100:
                        # Sayfayı pixmap olarak al
                        pix = page.get_pixmap(matrix=mat)
                        
                        # Büyük görüntüleri küçült
                        if pix.width > self.max_image_size or pix.height > self.max_image_size:
                            # PIL Image'a çevir
                            img_data = pix.tobytes("png")
                            img = Image.open(io.BytesIO(img_data))
                            
                            # Boyutu küçült
                            img.thumbnail((self.max_image_size, self.max_image_size), Image.Resampling.LANCZOS)
                            
                            # JPEG olarak kaydet
                            img_buffer = io.BytesIO()
                            if img.mode == 'RGBA':
                                img = img.convert('RGB')
                            img.save(img_buffer, format='JPEG', quality=self.quality, optimize=True)
                            img_data = img_buffer.getvalue()
                        else:
                            img_data = pix.tobytes("jpeg", jpg_quality=self.quality)
                        
                        # Geçici dosya oluştur
                        with tempfile.NamedTemporaryFile(suffix=".jpeg", delete=False) as tmp:
                            tmp.write(img_data)
                            tmp_path = tmp.name
                        
                        # Yeni sayfa oluştur ve görüntüyü ekle
                        new_page = new_doc.new_page(width=page.rect.width, height=page.rect.height)
                        new_page.insert_image(page.rect, filename=tmp_path)
                        
                        # Geçici dosyayı sil
                        os.unlink(tmp_path)
                        
                        # Bellek temizliği yap
                        del pix
                        if 'img' in locals():
                            del img
                        gc.collect()
                        
                    elif self.remove_images:
                        # Görüntüleri kaldır ve sadece metni koru
                        new_page = new_doc.new_page(width=page.rect.width, height=page.rect.height)
                        # Metni kopyala
                        text_dict = page.get_text("dict")
                        for block in text_dict["blocks"]:
                            if "lines" in block:  # Text block
                                for line in block["lines"]:
                                    for span in line["spans"]:
                                        new_page.insert_text(
                                            (span["bbox"][0], span["bbox"][1]),
                                            span["text"],
                                            fontsize=span["size"],
                                            color=(0, 0, 0)
                                        )
                    else:
                        # Sayfayı olduğu gibi kopyala
                        new_doc.insert_pdf(doc, from_page=page_num, to_page=page_num)
                    
                    # İlerlemeyi güncelle (sayfa bazında)
                    page_progress = int((page_num + 1) / total_pages * 50)  # Her dosya için %50
                    file_progress = int(i / total_files * 50)  # Dosyalar için %50
                    total_progress = file_progress + page_progress
                    self.progress_updated.emit(min(total_progress, 95))
                
                # Annotations'ları kaldır
                if self.remove_annotations:
                    for page in new_doc:
                        annot = page.first_annot
                        while annot:
                            next_annot = annot.next
                            page.delete_annot(annot)
                            annot = next_annot
                
                # Çıktı dosya yolu
                base_name = os.path.splitext(os.path.basename(file_path))[0]
                output_path = os.path.join(self.output_folder, f"{base_name}_compressed.pdf")
                
                # PDF'yi kaydet - Sıkıştırma seviyesine göre
                if self.compression_level == 0:  # Maksimum sıkıştırma
                    save_options = {
                        "garbage": 4,
                        "clean": True,
                        "deflate": True,
                        "deflate_images": True,
                        "deflate_fonts": True,
                        "linear": True,
                        "pretty": False
                    }
                elif self.compression_level == 1:  # Yüksek sıkıştırma
                    save_options = {
                        "garbage": 3,
                        "clean": True,
                        "deflate": True,
                        "deflate_images": True,
                        "deflate_fonts": self.compress_fonts,
                        "linear": False
                    }
                else:  # Normal sıkıştırma
                    save_options = {
                        "garbage": 1,
                        "clean": True,
                        "deflate": True,
                        "deflate_images": True,
                        "deflate_fonts": self.compress_fonts
                    }
                
                new_doc.save(output_path, **save_options)
                
                # Dosyaları kapat
                doc.close()
                new_doc.close()
                
                # Bellek temizliği
                gc.collect()
                
                # Boyut karşılaştırması
                original_size = os.path.getsize(file_path)
                compressed_size = os.path.getsize(output_path)
                reduction = (1 - compressed_size / original_size) * 100
                
                self.log_updated.emit(f"✓ Tamamlandı: {os.path.basename(file_path)}")
                self.log_updated.emit(f"  Orijinal boyut: {self.format_size(original_size)}")
                self.log_updated.emit(f"  Sıkıştırılmış boyut: {self.format_size(compressed_size)}")
                self.log_updated.emit(f"  Boyut azalması: {reduction:.1f}%")
                self.log_updated.emit("-" * 60)
                
                # Progress güncelle
                progress = int((i + 1) / total_files * 100)
                self.progress_updated.emit(progress)
            
            self.finished_signal.emit(True, "Tüm dosyalar başarıyla sıkıştırıldı!")
            
        except Exception as e:
            self.finished_signal.emit(False, f"Hata oluştu: {str(e)}")
    
    def format_size(self, size):
        """Dosya boyutunu okunabilir formatta döndür"""
        for unit in ['B', 'KB', 'MB', 'GB']:
            if size < 1024:
                return f"{size:.1f} {unit}"
            size /= 1024
        return f"{size:.1f} TB"


class PDFCompressorGUI(QMainWindow):
    def __init__(self):
        super().__init__()
        self.input_files = []
        self.output_folder = ""
        self.compressor_thread = None
        self.init_ui()
        
    def init_ui(self):
        self.setWindowTitle("PDF Boyut Küçültücü - Büyük Dosya Desteği")
        self.setGeometry(100, 100, 900, 700)
        
        # Ana widget
        main_widget = QWidget()
        self.setCentralWidget(main_widget)
        
        # Ana layout
        main_layout = QVBoxLayout(main_widget)
        main_layout.setSpacing(15)
        main_layout.setContentsMargins(20, 20, 20, 20)
        
        # Başlık
        title_label = QLabel("PDF Boyut Küçültücü")
        title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title_label.setFont(QFont("Arial", 18, QFont.Weight.Bold))
        title_label.setStyleSheet("color: #2E86C1; margin: 10px;")
        main_layout.addWidget(title_label)
        
        # Bilgi etiketi
        info_label = QLabel("30MB+ büyük PDF dosyaları için özel optimizasyonlar")
        info_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        info_label.setStyleSheet("color: #28B463; font-style: italic;")
        main_layout.addWidget(info_label)
        
        # Dosya seçimi grubu
        file_group = QGroupBox("📁 Dosya Seçimi")
        file_group.setStyleSheet("QGroupBox { font-weight: bold; }")
        file_layout = QVBoxLayout(file_group)
        
        # Dosya seçim butonları
        file_button_layout = QHBoxLayout()
        
        self.select_files_btn = QPushButton("📄 PDF Dosyalarını Seç")
        self.select_files_btn.clicked.connect(self.select_input_files)
        self.select_files_btn.setStyleSheet("""
            QPushButton {
                background-color: #3498DB;
                color: white;
                border: none;
                padding: 8px 16px;
                border-radius: 4px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #2980B9;
            }
        """)
        file_button_layout.addWidget(self.select_files_btn)
        
        self.select_output_btn = QPushButton("📂 Çıktı Klasörünü Seç")
        self.select_output_btn.clicked.connect(self.select_output_folder)
        self.select_output_btn.setStyleSheet("""
            QPushButton {
                background-color: #27AE60;
                color: white;
                border: none;
                padding: 8px 16px;
                border-radius: 4px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #229954;
            }
        """)
        file_button_layout.addWidget(self.select_output_btn)
        
        file_layout.addLayout(file_button_layout)
        
        # Seçilen dosyalar etiketi
        self.files_label = QLabel("Seçilen dosya yok")
        self.files_label.setWordWrap(True)
        self.files_label.setStyleSheet("color: #7F8C8D; padding: 5px;")
        file_layout.addWidget(self.files_label)
        
        # Çıktı klasörü etiketi
        self.output_label = QLabel("Çıktı klasörü seçilmedi")
        self.output_label.setWordWrap(True)
        self.output_label.setStyleSheet("color: #7F8C8D; padding: 5px;")
        file_layout.addWidget(self.output_label)
        
        main_layout.addWidget(file_group)
        
        # Sıkıştırma ayarları grubu
        settings_group = QGroupBox("⚙️ Sıkıştırma Ayarları")
        settings_group.setStyleSheet("QGroupBox { font-weight: bold; }")
        settings_layout = QGridLayout(settings_group)
        
        # Sıkıştırma seviyesi
        settings_layout.addWidget(QLabel("Sıkıştırma Seviyesi:"), 0, 0)
        self.compression_combo = QComboBox()
        self.compression_combo.addItems([
            "Maksimum Sıkıştırma (En küçük boyut)",
            "Yüksek Sıkıştırma (Önerilen)",
            "Normal Sıkıştırma (Hızlı)"
        ])
        self.compression_combo.setCurrentIndex(1)
        settings_layout.addWidget(self.compression_combo, 0, 1)
        
        # Kalite ayarı
        settings_layout.addWidget(QLabel("JPEG Kalitesi:"), 1, 0)
        quality_layout = QHBoxLayout()
        self.quality_slider = QSlider(Qt.Orientation.Horizontal)
        self.quality_slider.setRange(10, 95)
        self.quality_slider.setValue(50)
        self.quality_slider.valueChanged.connect(self.update_quality_label)
        self.quality_label = QLabel("50%")
        quality_layout.addWidget(self.quality_slider)
        quality_layout.addWidget(self.quality_label)
        settings_layout.addLayout(quality_layout, 1, 1)
        
        # DPI ayarı
        settings_layout.addWidget(QLabel("DPI (Çözünürlük):"), 2, 0)
        self.dpi_combo = QComboBox()
        self.dpi_combo.addItems(["72 (Web)", "96 (Standart)", "150 (İyi)", "200 (Yüksek)", "300 (Maksimum)"])
        self.dpi_combo.setCurrentIndex(1)  # 96 DPI
        settings_layout.addWidget(self.dpi_combo, 2, 1)
        
        # Maksimum görüntü boyutu
        settings_layout.addWidget(QLabel("Maks. Görüntü Boyutu:"), 3, 0)
        self.max_size_combo = QComboBox()
        self.max_size_combo.addItems([
            "800x800 (Çok küçük)",
            "1200x1200 (Küçük)", 
            "1600x1600 (Orta)",
            "2000x2000 (Büyük)",
            "2800x2800 (Çok büyük)"
        ])
        self.max_size_combo.setCurrentIndex(2)
        settings_layout.addWidget(self.max_size_combo, 3, 1)
        
        # Seçenekler
        options_layout = QHBoxLayout()
        
        self.remove_images_cb = QCheckBox("🖼️ Görüntüleri Kaldır")
        self.remove_images_cb.setToolTip("Tüm görüntüleri kaldırır, sadece metni korur")
        options_layout.addWidget(self.remove_images_cb)
        
        self.remove_annotations_cb = QCheckBox("📝 Açıklamaları Kaldır")
        self.remove_annotations_cb.setToolTip("Yorumları ve açıklamaları kaldırır")
        options_layout.addWidget(self.remove_annotations_cb)
        
        self.compress_fonts_cb = QCheckBox("🔤 Fontları Sıkıştır")
        self.compress_fonts_cb.setChecked(True)
        self.compress_fonts_cb.setToolTip("Font dosyalarını sıkıştırır")
        options_layout.addWidget(self.compress_fonts_cb)
        
        settings_layout.addLayout(options_layout, 4, 0, 1, 2)
        
        main_layout.addWidget(settings_group)
        
        # Kontrol butonları
        control_layout = QHBoxLayout()
        
        self.compress_btn = QPushButton("🚀 Sıkıştırmayı Başlat")
        self.compress_btn.clicked.connect(self.start_compression)
        self.compress_btn.setEnabled(False)
        self.compress_btn.setStyleSheet("""
            QPushButton {
                background-color: #E74C3C;
                color: white;
                border: none;
                padding: 12px 24px;
                border-radius: 6px;
                font-weight: bold;
                font-size: 14px;
            }
            QPushButton:hover {
                background-color: #C0392B;
            }
            QPushButton:disabled {
                background-color: #BDC3C7;
            }
        """)
        control_layout.addWidget(self.compress_btn)
        
        self.clear_btn = QPushButton("🗑️ Temizle")
        self.clear_btn.clicked.connect(self.clear_all)
        self.clear_btn.setStyleSheet("""
            QPushButton {
                background-color: #95A5A6;
                color: white;
                border: none;
                padding: 12px 24px;
                border-radius: 6px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #7F8C8D;
            }
        """)
        control_layout.addWidget(self.clear_btn)
        
        main_layout.addLayout(control_layout)
        
        # Progress bar
        self.progress_bar = QProgressBar()
        self.progress_bar.setVisible(False)
        self.progress_bar.setStyleSheet("""
            QProgressBar {
                border: 2px solid #BDC3C7;
                border-radius: 5px;
                text-align: center;
                font-weight: bold;
            }
            QProgressBar::chunk {
                background-color: #27AE60;
                border-radius: 3px;
            }
        """)
        main_layout.addWidget(self.progress_bar)
        
        # Log alanı
        log_group = QGroupBox("📋 İşlem Günlüğü")
        log_group.setStyleSheet("QGroupBox { font-weight: bold; }")
        log_layout = QVBoxLayout(log_group)
        
        self.log_text = QTextEdit()
        self.log_text.setMaximumHeight(250)
        self.log_text.setReadOnly(True)
        self.log_text.setStyleSheet("""
            QTextEdit {
                background-color: #2C3E50;
                color: #ECF0F1;
                border: 1px solid #34495E;
                border-radius: 4px;
                padding: 8px;
                font-family: 'Consolas', 'Monaco', monospace;
            }
        """)
        log_layout.addWidget(self.log_text)
        
        main_layout.addWidget(log_group)
        
        # Durum çubuğu
        self.statusBar().showMessage("Hazır - Büyük PDF dosyaları için optimize edildi")
        
    def update_quality_label(self, value):
        self.quality_label.setText(f"{value}%")
    
    def select_input_files(self):
        files, _ = QFileDialog.getOpenFileNames(
            self, 
            "PDF Dosyalarını Seç", 
            "", 
            "PDF Dosyaları (*.pdf)"
        )
        
        if files:
            self.input_files = files
            total_size = sum(os.path.getsize(f) for f in files)
            self.files_label.setText(f"{len(files)} dosya seçildi (Toplam: {self.format_size(total_size)})")
            self.log_text.append(f"✓ {len(files)} PDF dosyası seçildi:")
            for file in files:
                size = os.path.getsize(file)
                self.log_text.append(f"  📄 {os.path.basename(file)} - {self.format_size(size)}")
                if size > 30 * 1024 * 1024:  # 30MB+
                    self.log_text.append(f"    ⚠️ Büyük dosya tespit edildi")
            self.check_ready_to_compress()
    
    def select_output_folder(self):
        folder = QFileDialog.getExistingDirectory(
            self, 
            "Çıktı Klasörünü Seç"
        )
        
        if folder:
            self.output_folder = folder
            self.output_label.setText(f"Çıktı: {folder}")
            self.log_text.append(f"✓ Çıktı klasörü seçildi: {folder}")
            self.check_ready_to_compress()
    
    def check_ready_to_compress(self):
        if self.input_files and self.output_folder:
            self.compress_btn.setEnabled(True)
        else:
            self.compress_btn.setEnabled(False)
    
    def start_compression(self):
        if not self.input_files or not self.output_folder:
            QMessageBox.warning(self, "Uyarı", "Lütfen dosyaları ve çıktı klasörünü seçin!")
            return
        
        # UI'yi devre dışı bırak
        self.compress_btn.setEnabled(False)
        self.select_files_btn.setEnabled(False)
        self.select_output_btn.setEnabled(False)
        self.progress_bar.setVisible(True)
        self.progress_bar.setValue(0)
        
        # Ayarları al
        quality = self.quality_slider.value()
        
        # DPI değerini al
        dpi_map = {"72 (Web)": 72, "96 (Standart)": 96, "150 (İyi)": 150, 
                  "200 (Yüksek)": 200, "300 (Maksimum)": 300}
        dpi = dpi_map[self.dpi_combo.currentText()]
        
        # Maksimum görüntü boyutunu al
        size_map = {"800x800 (Çok küçük)": 800, "1200x1200 (Küçük)": 1200,
                   "1600x1600 (Orta)": 1600, "2000x2000 (Büyük)": 2000,
                   "2800x2800 (Çok büyük)": 2800}
        max_image_size = size_map[self.max_size_combo.currentText()]
        
        compression_level = self.compression_combo.currentIndex()
        remove_images = self.remove_images_cb.isChecked()
        remove_annotations = self.remove_annotations_cb.isChecked()
        compress_fonts = self.compress_fonts_cb.isChecked()
        
        # Sıkıştırma thread'ini başlat
        self.compressor_thread = PDFCompressorThread(
            self.input_files, self.output_folder, quality, dpi,
            remove_images, remove_annotations, compress_fonts,
            max_image_size, compression_level
        )
        self.compressor_thread.progress_updated.connect(self.update_progress)
        self.compressor_thread.log_updated.connect(self.update_log)
        self.compressor_thread.finished_signal.connect(self.compression_finished)
        self.compressor_thread.start()
        
        self.statusBar().showMessage("Sıkıştırma işlemi devam ediyor...")
        self.log_text.append("🚀 Sıkıştırma işlemi başlatıldı...")
        self.log_text.append("=" * 60)
    
    def update_progress(self, value):
        self.progress_bar.setValue(value)
    
    def update_log(self, message):
        self.log_text.append(message)
        self.log_text.verticalScrollBar().setValue(
            self.log_text.verticalScrollBar().maximum()
        )
    
    def compression_finished(self, success, message):
        # UI'yi yeniden etkinleştir
        self.compress_btn.setEnabled(True)
        self.select_files_btn.setEnabled(True)
        self.select_output_btn.setEnabled(True)
        self.progress_bar.setVisible(False)
        
        if success:
            self.statusBar().showMessage("Sıkıştırma tamamlandı!")
            self.log_text.append("🎉 " + message)
            QMessageBox.information(self, "Başarılı", message)
        else:
            self.statusBar().showMessage("Sıkıştırma başarısız!")
            self.log_text.append("❌ " + message)
            QMessageBox.critical(self, "Hata", message)
    
    def clear_all(self):
        self.input_files = []
        self.output_folder = ""
        self.files_label.setText("Seçilen dosya yok")
        self.output_label.setText("Çıktı klasörü seçilmedi")
        self.log_text.clear()
        self.progress_bar.setVisible(False)
        self.compress_btn.setEnabled(False)
        self.statusBar().showMessage("Temizlendi")
    
    def format_size(self, size):
        """Dosya boyutunu okunabilir formatta döndür"""
        for unit in ['B', 'KB', 'MB', 'GB']:
            if size < 1024:
                return f"{size:.1f} {unit}"
            size /= 1024
        return f"{size:.1f} TB"


def main():
    app = QApplication(sys.argv)
    
    # Fusion stilini ayarla
    app.setStyle('Fusion')
    
    # Modern koyu tema
    palette = QPalette()
    palette.setColor(QPalette.ColorRole.Window, QColor(45, 45, 48))
    palette.setColor(QPalette.ColorRole.WindowText, QColor(255, 255, 255))
    palette.setColor(QPalette.ColorRole.Base, QColor(30, 30, 30))
    palette.setColor(QPalette.ColorRole.AlternateBase, QColor(45, 45, 48))
    palette.setColor(QPalette.ColorRole.ToolTipBase, QColor(0, 0, 0))
    palette.setColor(QPalette.ColorRole.ToolTipText, QColor(255, 255, 255))
    palette.setColor(QPalette.ColorRole.Text, QColor(255, 255, 255))
    palette.setColor(QPalette.ColorRole.Button, QColor(45, 45, 48))
    palette.setColor(QPalette.ColorRole.ButtonText, QColor(255, 255, 255))
    palette.setColor(QPalette.ColorRole.BrightText, QColor(255, 0, 0))
    palette.setColor(QPalette.ColorRole.Link, QColor(42, 130, 218))
    palette.setColor(QPalette.ColorRole.Highlight, QColor(42, 130, 218))
    palette.setColor(QPalette.ColorRole.HighlightedText, QColor(0, 0, 0))
    app.setPalette(palette)
    
    # Ana pencereyi oluştur ve göster
    window = PDFCompressorGUI()
    window.show()
    
    sys.exit(app.exec())


if __name__ == '__main__':
    main()
