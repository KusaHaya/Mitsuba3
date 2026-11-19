# Mitsuba 3：LED・レンチキュラレンズの照射像シミュレーション

VS Codeで設定JSONを編集し、LED → レンズ → 受光面の照射分布を比較する研究用モデルです。
**入口は `simulate.py`、寸法設定は `configs/current.json` です。**

現在の既定条件は、受光面・レンズ外形546×312mm、左右対称のLED19本、LED―凸面頂点138.13mm、LED側追加PMMA10mm、スクリーン1.5mmです。比較は仕切りあり／仕切り＋中心40%開口。全体確認用preview2184×1248（0.25mm/画素）です。細い像幅はこのプレビューで評価しないでください。

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

### Windowsで描画中にJITエラーが出る場合（LLVM不要の互換CPUモード）

基本演算が成功しても、標準シーンが`Failed to materialize symbols`で停止するWindows環境があります。レンズ設定を変更する前に、LLVMのJITを使わない`scalar_rgb`を試せます。

```powershell
.\.venv\Scripts\python.exe simulate.py --variant scalar_rgb --spp 64 --case baseline --phase 0
```

F5では **照射像：Windows互換CPU（LLVM不要・低サンプル）** を選択します。まず1条件・1位相だけの低サンプル描画です。並列JITより遅く、64 sppの画像はノイズが多いため精密評価には使わないでください。描画が完了したら`--spp`を増やします。`--variant`と`--spp`の実際に使った値は`config_used.json`と`summary.json`に記録します。

互換モードを通常設定にする場合は`configs/current.json`の`render.variant`を`scalar_rgb`に変更できます。こちらで確認したのはLinux上のscalar描画です。Windowsでの実行はユーザー環境で確認が必要です。

### LLVMが見つからない場合

CPU並列の`llvm_ad_rgb`を選ぶ場合は、LLVMの共有ライブラリが必要です。現在の既定`scalar_rgb`ではLLVMは不要です。
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
| `optics.led_pitch_horizontal_mm` | 24.771175 | LEDバーに直角な中心間隔23.5mmを水平へ換算（縦:横=3:1） |
| `led_to_vertex_mm` | 138.13 | **LED発光面から凸面頂点まで**。平面入射面までではない |
| `rear_acrylic_mm` | 10.0 | レンズの平面側に密着した追加PMMAの厚さ。レンズ厚2mmとは別 |
| `screen_from_vertex_mm` | 1.5 | 凸面頂点から受光面まで |
| `screen_medium` | `pmma` | `pmma`または`air` |
| `mask.open_fraction` | 0.4 | 各レンズの中心部の開口率。0.4＝40% |
| `mask.z_mm` | 0.001 | 凸面頂点から理想マスク面まで |
| `baffles.height_mm` | 32.0 | LED面からレンズ方向への仕切り高さ |
| `baffles.thickness_mm` | 1.5 | 配列に直角な方向の壁厚 |
| `roi_mm` | [546,312] | x=−273～＋273mm、y=−156～＋156mm |
| `led_array.count` | 16 | 4の倍数。各位相同数、中央の位相0～3の中間をx=0にする |
| `optics.lens_count` | 900 | モデル化するレンズ数（偶数） |
| `optics.v_length_mm` | 60.0 | 円筒軸方向のモデル長さ |
| `optics.segments_per_lens` | 128 | 1周期の曲面分割数 |
| `render.preview` | 2184×1248 / 512 spp | 動作・傾向の確認用 |
| `render.quality` | 4368×2496 / 2048 spp | 時間がかかる比較用。精度保証ではない |

JSONでは`1/3`のような式やコメントは使えません。`0.3333333333333333`と入力します。
焦点距離1.023mmは直接指定しません。曲率と屈折率から屈折を計算します。現設定の空気中の近軸有効焦点距離は`R/(n-1) ≈ 1.020408 mm`です。焦点距離を合わせるために実物と異なる屈折率へ無条件に変更しないでください。

### 4位相グループの中央とLED数

`led_array.count=16`では16本を左右対称に配置し、位相0～3を各4本点灯します。中央4本の水平位置（バーのy=0での交点）は次のとおりです。

| 位相 | 水平位置 |
|---|---:|
| 0 | −34.05mm |
| 1 | −11.35mm |
| 2 | ＋11.35mm |
| 3 | ＋34.05mm |

LED間の仕切りはそれぞれの中間に置きます。これまでの「位相0のLEDが原点、LED9本、各位相3/2/2/2本」とは原点と光源の範囲が変わっています。距離だけを変えた実験ではありません。距離変更の効果だけを比較するときは、同じ新設定で`led_to_vertex_mm`だけを120/125に変えてください。

旧120mm・中央8×8mm・LED9本の設定は`configs/previous_120_central8mm.json`に保存しています。`led_array`がない設定では旧配置を維持します。以前の結果を`--plot-only`で開くと、その結果の設定を読み込むので、新しい±35mmの計算に変わることはありません。

レンズメッシュも新しい受光範囲に合わせて120周期×軸方向60mmへ拡張しました。これは部分モデルの範囲で、実機全体のレンズサイズではありません。画像の縦横比はROIと一致させてください（70:8なら2240:256）。

### 比較する条件

`cases`は以下の名前の配列です。

- `baseline`：マスクなし・仕切りなし
- `mask`：マスクあり・仕切りなし
- `baffles`：仕切りあり・マスクなし
- `mask_baffles`：両方あり

たとえば、マスク有無だけなら`"cases": ["baseline", "mask"]`。
現在は`"cases": ["baffles", "mask_baffles"]`です。単独の条件や位相をCLIで指定することもできます。

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
- `条件_phase番号.csv`：レンズ配列に直角な座標で1周期に折り畳んだ相対値・画素数。
- `条件_phase番号_horizontal.csv`：折り畳まない水平全範囲の縞方向平均・画素数。
- `led_layout.json`：実際に使用したLED番号・位相・水平位置（バーのy=0での交点）。
- `lens.ply`：計算に使ったレンズメッシュ。

### 各位相を別々に見る

新しい計算では、`phase_0.png`、`phase_1.png`、`phase_2.png`、`phase_3.png`も出力します。各ファイルの上段・下段は**同じ位相だけ**です。上段は1周期に折り畳まず、水平範囲全体（現在は−35～＋35mm）を示します。縞が斜めなので、各行を`x+slope*y`で整列し、縞に沿って平均したy=0換算の水平分布です。画像の1行を抜いただけの値ではありません。端で範囲外になる画素はゼロ扱いせず平均から除外します。列は条件別で、グラフの縦軸と照射像の色尺度は4位相・全条件で共通です。強さの差を隠す位相ごとの最大値正規化はしません。`overview.png`は従来の重ね描きとして残します。

保存済みの計算からも、光線を再計算せず作成できます。

```powershell
.\.venv\Scripts\python.exe simulate.py --plot-only latest
```

`latest`は`results/`内で`summary.json`が最後に更新された結果を使い、ターミナルに選択したフォルダを表示します。特定の結果を選ぶ場合:

```powershell
.\.venv\Scripts\python.exe simulate.py --plot-only .\results\20261118_190927_931590
```

VS CodeのF5でも「結果：4位相を別々に表示（再計算なし・最新の結果）」を選択できます。実際に計算した位相だけが出力されます。元の`.npy`、CSV、設定は変更しません。

`overview.png`の上段は全位相・全条件で共通の縦軸です。下段の色範囲は条件ごとに設定しているので、色だけで条件間の光量を比較しないでください。
`overview.png`と通常CSVの折り畳み周期は、有限物体距離と受光面の媒質を考慮した**近似値**です。周期の実測値ではありません。折り畳むことで周期ごとの違いが隠れるため、必ず2D分布と合わせて確認します。空のビンはゼロではなくNaNとして残します。

## 下段の4位相照射像を重ねて見る

`simulate.py --plot-only latest`で、保存した数値分布から次も生成します。光線を再計算する必要はありません。

- `phase_overlay.png`：評価範囲全体の4位相重ね合わせ。
- `phase_overlay_zoom.png`：同じデータの中央±1.5mm拡大。細い縞の位置関係を見るための図。
- `条件_phase_overlap.npz`：合計値、各位相の割合、非最大位相比を保存。
- `phase_overlay_notes.json`：計算式、色、表示上の閾値を記録。

画像の上段は、位相0＝青、1＝橙、2＝緑、3＝赤で、同じ位置に届く各位相の強さを色混合しています。明るさは4位相の合計を共通尺度で表示しています。色が混ざっても、その色だけから位相の組み合わせを一意に逆算することはできません。

下段は`1 − 最大の位相の強さ / 4位相の合計`です。0なら1位相だけ、0.5なら2位相が等しい場合、0.75なら4位相が等しい場合です（一般に他の組み合わせでも同じ値を取り得ます）。灰色は合計値が共通表示基準の1%以下で、暗すぎるため比率の表示を省いた場所です。この閾値は表示用で、数値配列そのものは保存します。

**これは別々の時刻の照射像を同じ座標で比較した図です。実際の同時点灯像や、LCD画像・観察者を含むクロストーク率ではありません。** 計算ノイズや弱い迷光も比率に影響します。4位相すべてを計算済みの条件だけ重ね合わせを作ります。PNGのカラーマップを合成するのではなく、`.npy`の線形数値を使用します。

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

## 2026-11-19 LED間隔の訂正

LEDバーに直角な中心間隔23.5mmから、水平方向を24.771175mmへ訂正しました。訂正直後は125mm・スクリーン1.5mmで比較しました。現在の既定は下の採用設計です。以前の22.7mmの結果と混同しないでください。

設計再計算は `python recalculate_design.py`。計算式、スクリーン位置ごとの幅・中心間隔、仕切り高さの条件は [再計算資料](docs/recalculated_235normal.md) を参照してください。

## 採用設計：138.13mm＋LED側アクリル10mm

`configs/current.json`を更新しました。追加アクリルはレンズ平面側に密着し、同じ屈折率1.49のPMMAとして扱います。内部に仮の空気界面を作らず、メッシュの底面だけをz=-2mmから-12mmへ延長しています。凸面頂点・溝形状は動かしません。実機の微小空隙・接着層は含みません。

`rear_acrylic_mm`を省略した旧設定は0mmとして実行できます。直前の125mm設定は`configs/previous_125_corrected_pitch.json`に保存しました。[今回の条件と近軸値](docs/accepted_13813_rear10.md)を参照してください。

```powershell
git pull
.\.venv\Scripts\python.exe simulate.py --variant scalar_rgb --spp 512
```

## World xを±35mmへ拡張

既定比較は仕切りあり`baffles`と仕切り＋中心40%開口`mask_baffles`の2条件です。`--case`指定なしで両方の全4位相を計算します。仕切りなし条件は明示指定した場合のみです。

受光面を70×8mm、レンズクロップを120周期（溝直角方向84mm）へ拡張しました。光源本数16本・LED寸法・距離・仕切り・開口率は変更しません。preview2240×256、quality4480×512とし、水平ピクセル幅0.03125mm／0.015625mmを従来から維持します。計算量は増えます。以前の±23mm条件は`configs/previous_13813_rear10_pm23.json`です。

範囲拡張で全体を折り重ねた平均分布の重みは変わります。中央の局所的な異位相の近接が解消することを保証する変更ではありません。新旧比較では同じ中央領域を切り出して確認してください。

## 全画面546×312mm・LED19本

現在の既定は全画面。詳細は[全画面設定](docs/full_display_19led.md)を参照。連続配置の左端を位相0、以降0→1→2→3と仮定し、位相ごとの本数は5/5/5/4です。19本の中央のLEDを原点とします。実配線の開始位相が違う場合は`led_array.first_phase`を0～3で変更できます。19本を均等な本数にはできません。

LEDバーの実寸長は未指定のため、表示高さ312mmを覆う直線バー（長さ328.877mm）として仮定しました。`led_array.bar_length_mm`で実寸へ変更できます。レンズ軸方向の計算サイズとは独立した値です。

全体プレビューは0.25mm/画素で、約0.03mmの像幅は測定できません。従来と同じ0.03125mm/画素を保つ`configs/full_display_fine.json`も用意しました。17472×9984画素のNPYが1条件あたり約0.70GB、8条件で約5.58GBとなり、描画・後処理にはさらにRAMとディスクを使います。必要に応じて位相を限定し、まず1条件で確認してください。

```powershell
# 全体確認用（既定：仕切りあり／仕切り＋マスクの全4位相）
.\.venv\Scripts\python.exe simulate.py --variant scalar_rgb --spp 512
# 従来の画素密度。まず1条件・1位相のみを確認
.\.venv\Scripts\python.exe simulate.py --config configs/full_display_fine.json --variant scalar_rgb --case mask_baffles --phase 0 --spp 512
```

旧±35mm・16本の設定は`configs/previous_13813_rear10_pm35.json`に保存。全画面化・19本化・LED有限長・レンズ外形の変更を含むので、ROIだけを変えた比較ではありません。

## GPUでメモリ不足になる場合

GPU既定の処理単位を1spp/passに変更しました。全体のsppは変えず、512sppを512回に分けます。全画面preview2184×1248の場合、1passのprimary samplesは旧256spp/passの697,761,792から2,725,632になります。固定のシーン・画像バッファもあるため、VRAMが正確に256分の1になるという意味ではありません。GPU11GBでの動作は実機で未検証です。

```powershell
git pull
.\.venv\Scripts\python.exe simulate.py --variant cuda_ad_rgb --spp 512 --samples-per-pass 1
```

`--samples-per-pass`は1回の処理上限で、総サンプル数を割り切る値に調整されます。実際の値とpass数を起動時に表示し、config_used.jsonのrender.samples_per_passへ保存します。指定を省略してもGPUでは1です。CPUでは従来どおり最大256です。サンプル列は分割方法により変わり得るため、前の画像と画素単位では一致しません。

位相計算の間だけGPUの未使用割当キャッシュを解放します。内側の各passでは解放しません。レンズPLYもbinary little endian形式へ変更し、ASCII読み込み警告と読み込み時間を減らしました。形状・材質・解像度・総spp・光学条件は変更しません。

1spp/passでも不足する場合は画像解像度を下げてください。総sppだけを減らしても、1passのメモリは減りません。巨大なfull_display_fine.jsonはGPU11GBで動くことを保証していません。今回の対処は既定プレビュー向けです。`evaluate=true`への自動変更警告はmulti-pass時に引き続き出る場合があります。
