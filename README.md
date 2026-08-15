# Disk Space Analyzer

用互動式區塊圖（treemap）找出磁碟裡的容量怪獸——哪些資料夾佔用了最多空間。單一 EXE、免安裝、內建自動更新。

## 下載使用

到 [Releases](../../releases/latest) 下載 `DiskSpaceAnalyzer.exe`，雙擊執行即可，不需要安裝。

- 需要 Windows 10/11，且系統已內建 WebView2 Runtime（Windows 11 預設已內建；Windows 10 多數也已透過 Edge 更新內建，若缺少會由 Windows Update 自動補上）。
- 開啟後選擇磁碟或資料夾，按「開始掃描」，掃描完成後可在區塊圖中點擊鑽入子資料夾，或切換成表格檢視。
- 雙擊區塊或表格中的路徑可直接在檔案總管開啟該資料夾。
- 每次啟動會自動檢查是否有新版本，若有會在畫面上方提示，按「立即更新」即可自動下載並重啟。

## 開發

```bash
pip install -r requirements.txt
python app.py
```

## 打包（本機測試用）

```bash
pip install pyinstaller
pyinstaller --onefile --windowed --name DiskSpaceAnalyzer --add-data "ui.html;." app.py
```

正式發布版本由 GitHub Actions 自動打包：推送一個 `vX.Y.Z` 格式的 tag 就會觸發 `.github/workflows/release.yml`，自動建置並發布到 GitHub Release。

```bash
git tag v1.0.1
git push origin v1.0.1
```

發布前記得同步更新 [`version.py`](version.py) 裡的 `APP_VERSION`。
