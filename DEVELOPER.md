```markdown
# Geliştirici Dokümantasyonu – PDF Boyut Küçültücü

## Yapı

- `PDFCompressorGUI`: Ana PyQt GUI sınıfı
- `PDFCompressorThread`: PDF işlemlerini arka planda yürüten iş parçacığı
- `main()`: GUI başlatma fonksiyonu

## Modüller

- `fitz` (PyMuPDF): PDF okuma/yazma
- `PIL` (Pillow): Görüntü işleme
- `QThread`: Arka plan iş parçacığı
- `QSlider/QSpinBox/QCheckBox`: UI kontrolleri
- `QProgressBar`: İşlem ilerlemesi

## Özellikler

- Büyük dosyalar için agresif sıkıştırma
- Sayfa çözünürlüğü DPI’a göre yeniden render edilir
- Görsel kaldırıldığında metin yapısı korunur
- Geçici dosya kullanımı ve `gc.collect()` ile bellek optimizasyonu

## UI Öğeleri

- `QGroupBox` ile mantıksal bölümler (Dosya Seçimi, Ayarlar vb.)
- `QTextEdit` ile canlı loglama
- `QMessageBox` ile hata/success bildirimi

## Geliştirme İpuçları

- Yeni sıkıştırma seviyeleri için `PDFCompressorThread.run()` içinde `save_options` geliştirilebilir
- Çok dilli destek için `.ts/.qm` çeviri sistemine uygun yapıya dönüştürülebilir
- Arayüz QSS ile tamamen özelleştirilebilir
