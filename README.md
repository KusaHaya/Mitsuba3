# Mitsuba 3：LED・レンチキュラレンズの照射像シミュレーション

VS Codeで設定JSONを編集し、LED → レンズ → 受光面の照射分布を比較する研究用モデルです。
**入口は `simulate.py`、寸法設定は `configs/current.json` です。**

## Windows / VS Codeで使う

1. 64bitのPython **3.12**、VS Codeをインストールします。
2. このリポジトリをクローンし、**リポジトリのフォルダそのもの**をVS Codeで開きます。
3. 拡張機能 **Python** と **Python Debugger**（Microsoft）をインストールします。
4. VS Codeのターミナル（PowerShell）で実行します。

```powershell
.\setup_windows.ps1
```

このスクリプトはプロジェクト内に`.venv`を作成し、依存パッケージをインストールします。PowerShellのポリシーでスクリプトを実行できない場合、ポリシーを変えず、次のコマンドを直接実行できます。

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

5. `Ctrl+Shift+P` → **Python: Select Interpreter** → `.venv\Scripts\python.exe`を選択します。
6. 「実行とデバッグ」で **照射像：プレビュー（設定JSON）** を選び、F5で実行します。
7. ターミナルに表示された`results/日時/`を開き、`overview.png`を見ます。

ターミナルからも同じ計算を実行できます。仮想環境の有効化は必須ではありません。

```powershell
.\.venv\Scripts\python.exe simulate.py
```

### LLVMが見つからない場合

標準設定はCPUの`llvm_ad_rgb`です。LLVMの共有ライブラリが必要です。
[LLVMの公式リリース](https://github.com/llvm/llvm-project/releases)から、対応する64bit Windows版を導入してください。PythonとLLVMのアーキテクチャを合わせます。
`LLVM-C.dll`が見つからないエラーでは、DLLの実在を確認したうえで、VS Codeを起動する前の環境変数、またはVS Codeのターミナルで次を設定します。

```powershell
$env:DRJIT_LIBLLVM_PATH = "C:\Program Files\LLVM\bin\LLVM-C.dll"
.\.venv\Scripts\python.exe simulate.py
```

`DRJIT_LIBLLVM_PATH`は**フォルダではなくDLLファイル**を指定します。F5で実行する場合は、Windowsの環境変数へ設定してVS Codeを再起動するか、`.vscode/launch.json`の該当構成に`"env": {"DRJIT_LIBLLVM_PATH": "C:\\Program Files\\LLVM\\bin\\LLVM-C.dll"}`を追加してください。DLL依存関係のためLLVMの`bin`をPATHへ加える必要がある場合もあります。
NVIDIA GPUを利用できる環境では、JSONの`render.variant`を`cuda_ad_rgb`に変更する選択肢もありますが、GPUやドライバの対応は別途確認が必要です。

**確認範囲：Linux CPU / Mitsuba 3.9.1でテストと実描画を実施。WindowsのVS Code実機では未確認です。**

## 自分で変更する設定

`configs/current.json`を編集・保存して再実行します。寸法はmmです。

| JSON項目 | 標準値 | 定義 |
|---|---:|---|
| `optics.pitch_mm` | 0.7 | レンズ配列に直角な周期 |
| `optics.radius_mm` | 0.5 | 円弧断面の曲率半径 |
| `optics.thickness_mm` | 2.0 | 凸面頂点から平面入射面までの厚さ |
| `optics.ior` | 1.49 | PMMAの屈折率（波長依存なし） |
| `optics.normal_slope` | 1/3相当の小数 | 配列の面内法線を(1, slope)と定義。円筒軸はこれに直角 |
| `optics.led_width_horizontal_mm` | 3.0 | LEDの水平発光幅 |
| `optics.led_pitch_horizontal_mm` | 22.7 | LEDの水平中心間隔 |
| `led_to_vertex_mm` | 120.0 | **LED発光面から凸面頂点まで**。平面入射面までではない |
| `screen_from_vertex_mm` | 1.5 | 凸面頂点から受光面まで |
| `screen_medium` | `pmma` | `pmma`または`air` |
| `mask.open_fraction` | 0.4 | 各レンズの中心部の開口率。0.4＝40% |
| `mask.z_mm` | 0.001 | 凸面頂点から理想マスク面まで |
| `baffles.height_mm` | 32.0 | LED面からレンズ方向への仕切り高さ |
| `baffles.thickness_mm` | 1.5 | 配列に直角な方向の壁厚 |
| `roi_mm` | [8,8] | 中央で評価する幅・高さ。全画面ではない |
| `optics.lens_count` | 40 | モデル化するレンズ数（偶数） |
| `optics.v_length_mm` | 30.0 | 円筒軸方向のモデル長さ |
| `optics.segments_per_lens` | 128 | 1周期の曲面分割数 |
| `render.preview` | 256×256 / 512 spp | 動作・傾向の確認用 |
| `render.quality` | 512×512 / 2048 spp | 時間がかかる比較用。精度保証ではない |

JSONでは`1/3`のような式やコメントは使えません。`0.3333333333333333`と入力します。
焦点距離1.023mmは直接指定しません。曲率と屈折率から屈折を計算します。現設定の空気中の近軸有効焦点距離は`R/(n-1) ≈ 1.020408 mm`です。焦点距離を合わせるために実物と異なる屈折率へ無条件に変更しないでください。

### 比較する条件

`cases`は以下の名前の配列です。

- `baseline`：マスクなし・仕切りなし
- `mask`：マスクあり・仕切りなし
- `baffles`：仕切りあり・マスクなし
- `mask_baffles`：両方あり

たとえば、マスク有無だけなら`"cases": ["baseline", "mask"]`。
単独の条件や位相をCLIで指定することもできます。

```powershell
.\.venv\Scripts\python.exe simulate.py --case mask --phase 0
.\.venv\Scripts\python.exe simulate.py --mode quality
.\.venv\Scripts\python.exe simulate.py --config configs/current.json --validate-only
```

`--case`と`--phase`は複数回指定できます。F5の引数は`.vscode/launch.json`にあります。

## 結果の見方

毎回、新しい日時フォルダへ保存します。既存の非空フォルダを`--output`に指定するとエラーになります。条件変更後に古い`.npy`を再利用しないためです。

- `config_used.json`：使った設定値の完全なコピー。
- `summary.json`：バージョン、設定、各位相の平均値、計算時間、限界。
- `overview.png`：上段＝周期折り畳み分布、下段＝各条件で最初に描画した位相の2D分布。
- `条件_phase番号.npy`：線形の相対受光分布。
- `条件_phase番号.csv`：レンズ配列に直角な座標、相対値、平均に使った画素数。
- `lens.ply`：計算に使ったレンズメッシュ。

上段は全位相・全条件で共通の縦軸です。下段の色範囲は条件ごとに設定しているので、色だけで条件間の光量を比較しないでください。
折り畳み周期は、有限物体距離と受光面の媒質を考慮した**近似値**です。周期の実測値ではありません。折り畳むことで周期ごとの違いが隠れるため、必ず2D分布と合わせて確認します。空のビンはゼロではなくNaNとして残します。

## 光学モデルの範囲と限界

- 周期的な円弧円筒レンズを三角形メッシュで形成し、実際に屈折・Fresnel反射を追跡します。非球面ではありません。
- LEDは均一なLambertian長方形で、円筒軸に沿うバーに近似。水平幅と間隔は配列法線方向へ投影します。実測配光やLEDパッケージは含みません。
- `pmma`は溝内の空気を残し、レンズ後方をPMMAで満たし、その内部に理想拡散受光面を置く近似です。実物のアクリル①→レンズ→アクリル②→スクリーン→アクリル③→LCDの全積層やスクリーンの散乱特性は再現しません。
- 仕切りは隣接LEDの中央にある直方体・完全吸収壁です。3Dプリンタ製の溝、丸み、反射・散乱は未実装。高さ32mm・厚み1.5mmは仮定値です。
- RGBの非分散モデル。色収差、回折、液晶画像・応答、視域、観察者は含みません。
- 予備検証のレンズなし基準シーンには約11%の正規化差が残っています。絶対輝度や実機のクロストークとして解釈しないでください。
- **半値幅やクロストーク率は自動的に確定表示しません。** `summary.json`ではnullにし、未検証である理由を保存します。
- 高品質モードも収束済みという意味ではありません。光線数・画素数・メッシュ分割数を個別に変え、基準計算と実測に照合する必要があります。

## 開発・テスト

```powershell
.\.venv\Scripts\python.exe -m pytest -q
```

`tests/test_simulate.py`では距離基準、無効な設定の拒否、折り畳みの座標・欠測扱い、Mitsubaで4種類の条件を実際に描画できることを確認します。これは物理精度の保証ではありません。

旧コードの説明は[docs/legacy_readme.md](docs/legacy_readme.md)。旧`reproduce_unity.py`の構文エラーと`ptracer`用カメラを修正しましたが、旧解析の数値を検証済み性能として使わないでください。通常は新しい`simulate.py`を使用します。
