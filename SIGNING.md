# Windows署名付き配布（Ver 0.16）

Windows 11、Python 3.12、Windows SDKのSignTool、秘密鍵を利用できるコード署名証明書が必要です。証明書はCurrentUser\\Myに登録します。LocalMachine\\Myを使う場合は`-MachineStore`を追加します。秘密鍵や証明書ファイルはソースやGitに入れません。

```powershell
.\windows.ps1 -CertificateThumbprint "証明書のSHA-1拇印"
```

環境変数`PSTBSKX_SIGN_CERT_SHA1`で拇印を指定してもかまいません。別のRFC 3161タイムスタンプサーバーを使う場合は`-TimestampUrl`で指定します。署名証明書が未指定・無効、SignTool未導入、署名・タイムスタンプ・検証に失敗した場合は、その時点で停止して配布ZIPを作りません。

`windows.ps1`はテスト→PyInstaller EXE生成→ステージング→EXE署名・タイムスタンプ→`signtool verify /pa /v /tw`→更新マニフェスト作成→ZIP圧縮の順に実行します。更新機能のハッシュは署名後のEXEを対象とするため、署名後にEXEを改変しないでください。

完成物は`release/PSTBSK-X_0.16_win64.zip`です。展開したEXEのプロパティまたはSignToolで発行者・署名・タイムスタンプを確認してください。作者表示とライセンス原文はアプリのヘルプ→ライセンス、配布ZIPの`licenses/`で確認できます。ソースZIP自体はWindows更新用ZIPではありません。

開発環境はLinuxのためWindowsビルドと実証明書による署名は実行できません。利用者のWindows上で実行し、最終ZIPを確認してください。
