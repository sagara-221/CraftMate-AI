// main.dart
import 'package:flutter/material.dart';
import 'package:dotted_border/dotted_border.dart';
import 'package:google_fonts/google_fonts.dart';
import 'package:flutter_dotenv/flutter_dotenv.dart';
import 'package:flutter/foundation.dart';
import 'package:pointer_interceptor/pointer_interceptor.dart';

import 'dart:html' as html;
import 'dart:ui_web' as ui;
import 'dart:math';
import 'dart:convert';
import 'package:http/http.dart' as http;
import 'dart:async';
import 'package:http_parser/http_parser.dart';
import 'dart:typed_data';

// ------------------------------------------------------------------
// ▼ グローバル状態
// ------------------------------------------------------------------
List<Part>? _allParts;
late html.IFrameElement _iframeElement;
late html.IFrameElement _stepIframeElement;
html.File? _droppedImageFile;
String? _previewImageUrl;
String? _planId;
// 送信待ちのデータを一時保持
Map<String, dynamic>? _pendingModelData;
Map<String, dynamic>? _pendingStepData;
// デザイン用変数
// ────────────────────────────────────────────────────────────────
//  Topカードサイズ定数
// ────────────────────────────────────────────────────────────────
const double _topCardHeight = 350;
const double kBreakNarrow = 600.0; // 幅がこれ未満なら縦レイアウト
// ────────────────────────────────────────────────────────────────
//  手順ビュー用サイズ定数
// ────────────────────────────────────────────────────────────────
const double kStepViewerBreak = 720.0; // Row / Column 切替幅
const double kStepViewerRowRatio = 0.48; // Row 時の幅割合
const double kStepViewerColRatio = 0.90; // Column 時の幅割合
const double kStepViewerMaxWidth = 400.0; // 上限幅
const double kStepViewerAspect = 4 / 3; // 幅 : 高さ（4:3）
// API制御
const Duration kPollInterval = Duration(seconds: 10);
const int kMaxAttempts = 100;

// ------------------------------------------------------------------
// ▼ エントリーポイント
// ------------------------------------------------------------------
void main() async {
  await dotenv.load(fileName: '.env');
  const viewId = 'three-iframe';

  /* ------- 完成モデル用 iframe ------- */
  _iframeElement = html.IFrameElement()
    // ★ここを変更
    ..src = 'assets/three_obj_viewer.html?role=assembled'
    ..style.border = 'none'
    ..width = '100%'
    ..height = '100%';

  /* ------- 手順モデル用 iframe ------- */
  _stepIframeElement = html.IFrameElement()
    // ★ここを変更
    ..src = 'assets/three_obj_viewer.html?role=step'
    ..style.border = 'none'
    ..width = '100%'
    ..height = '100%';

  _iframeElement.onLoad.listen((_) {
    if (_pendingModelData != null) {
      _iframeElement.contentWindow?.postMessage(_pendingModelData, '*');
    }
  });
  ui.platformViewRegistry.registerViewFactory(viewId, (int viewId) {
    return _iframeElement;
  });

  _stepIframeElement.onLoad.listen((_) {
    if (_pendingStepData != null) {
      _stepIframeElement.contentWindow?.postMessage(_pendingStepData, '*');
    }
  });

  ui.platformViewRegistry.registerViewFactory('step-three-iframe', (
    int viewId,
  ) {
    return _stepIframeElement;
  });

  // 新しいテーマ適用
  runApp(
    MaterialApp(
      debugShowCheckedModeBanner: false,
      theme: ThemeData(
        scaffoldBackgroundColor: const Color(0xFFF3F6FF),
        cardColor: Colors.white,
        textTheme: GoogleFonts.notoSansTextTheme(),
        elevatedButtonTheme: ElevatedButtonThemeData(
          style: ElevatedButton.styleFrom(
            backgroundColor: const Color(0xFF5566FF),
            foregroundColor: Colors.white,
            shape: RoundedRectangleBorder(
              borderRadius: BorderRadius.circular(20),
            ),
            padding: const EdgeInsets.symmetric(vertical: 14, horizontal: 32),
          ),
        ),
      ),
      home: const MainPage(),
    ),
  );
}

// ------------------------------------------------------------------
// ▼ API ラッパー
// ------------------------------------------------------------------
String get authToken => dotenv.env['AUTH_TOKEN'] ?? '';
Map<String, String> authHeaders() => {'Authorization': 'Bearer $authToken'};
// 画像アップロード
Future<String> uploadImageToServer(html.File file) async {
  // ★ 1) ベース URL を .env から取っても OK
  final baseUrl = dotenv.env['API_BASE'] ?? 'http://localhost:8000';
  final uri = Uri.parse('$baseUrl/api/upload');

  final request = http.MultipartRequest('POST', uri)
    // ★ 2) 認可ヘッダを追加
    ..headers['Authorization'] = 'Bearer ${dotenv.env['AUTH_TOKEN'] ?? ''}';

  // ファイルを Uint8List に
  final fileBytes = await fileToUint8List(file);

  request.files.add(
    http.MultipartFile.fromBytes(
      'file',
      fileBytes,
      filename: file.name,
      contentType: MediaType('image', 'png'),
    ),
  );

  // 送信
  final response = await request.send();

  // ★ 3) 200 以外の場合もレスポンス本文を読んでデバッグしやすく
  final body = await response.stream.bytesToString();
  if (response.statusCode == 200) {
    final json = jsonDecode(body);
    final planId = json['plan_id'] as String;

    // デバッグ用
    if (kDebugMode) {
      final decoded = jsonDecode(body);
      final pretty = const JsonEncoder.withIndent('  ').convert(decoded);
      debugPrint('[DEBUG] upload レスポンス: $pretty');
    }

    return planId;
  } else {
    throw Exception(
      'アップロード失敗: '
      '${response.statusCode} ${response.reasonPhrase}\n$body',
    );
  }
}

/// OBJ 取得
Future<String> fetchAssembledModelOBJText(String planId) async {
  // .env → 例: API_BASE=http://localhost:8000
  final apiBase = dotenv.env['API_BASE'] ?? 'http://localhost:8000';
  final baseUrl = '$apiBase/api/$planId';

  // ── planId が UUID か簡易チェック ───────────────────
  final uuidReg = RegExp(
    r'^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-'
    r'[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$',
  );
  if (!uuidReg.hasMatch(planId)) {
    throw FormatException('planIdがUUID形式ではありません');
  }
  // ── モデル準備完了をポーリング ────────────────────
  const maxAttempts = kMaxAttempts;
  const pollInterval = kPollInterval;

  final authHeader = {
    'Authorization': 'Bearer ${dotenv.env['AUTH_TOKEN'] ?? ''}',
  };

  for (var i = 0; i < maxAttempts; i++) {
    final readyRes = await http.get(
      Uri.parse('$baseUrl/model/ready'),
      headers: authHeader,
    );

    if (readyRes.statusCode == 200) {
      final json = jsonDecode(readyRes.body);
      if (json['ready'] == true) break; // 準備完了なら抜ける
    } else {
      throw Exception(
        'モデル準備確認APIが失敗: '
        '${readyRes.statusCode} ${readyRes.reasonPhrase}',
      );
    }

    // 30 秒待って次のループへ
    if (i == maxAttempts - 1) {
      throw TimeoutException('モデルの準備がタイムアウトしました');
    }
    await Future.delayed(pollInterval); // ← ★ ここを変更
  }

  // ── OBJ 取得 ──────────────────────────────────────
  final modelRes = await http.get(
    Uri.parse('$baseUrl/model'),
    headers: authHeader,
  );

  if (modelRes.statusCode == 200) {
    final body = modelRes.body;

    if (kDebugMode) {
      debugPrint('[DEBUG] OBJ レスポンス:\n$body');
    }

    return body;
  }

  // 失敗時はレスポンス本文も添えて例外
  throw Exception(
    'モデル取得失敗: '
    '${modelRes.statusCode} ${modelRes.reasonPhrase}\n${modelRes.body}',
  );
}

/// OBJ から色マップ付きレンダリング用データを生成
Future<Map<String, dynamic>> fetchAssembledModelRenderDataFromOBJ(
  String objText,
) async {
  if (_planId == null) throw Exception('planId 未設定');

  final RegExp groupExp = RegExp(r'^\s*g\s+(\S+)', multiLine: true);
  final matches = groupExp
      .allMatches(objText)
      .map((m) => m.group(1)!.trim())
      .toSet()
      .toList();

  final parts = await fetchAllParts(_planId!);

  final groupColors = <String, String>{};
  for (final groupName in matches) {
    final match = parts.firstWhere(
      (p) => p.name == groupName,
      orElse: () => Part(groupName, 'nothing', Colors.grey),
    );
    final c = match.color;
    final hex =
        '#${c.red.toRadixString(16).padLeft(2, '0')}${c.green.toRadixString(16).padLeft(2, '0')}${c.blue.toRadixString(16).padLeft(2, '0')}';
    groupColors[groupName] = hex;
  }
  final normalisedObj = objText.split('\n').map((l) => l.trimLeft()).join('\n');

  return {'objText': normalisedObj, 'groupColors': groupColors};
}

// 部品一覧取得
Future<List<Part>> fetchAllParts(String planId) async {
  // すでにキャッシュ済みなら再取得しない
  if (_allParts != null) return _allParts!;

  final apiBase = dotenv.env['API_BASE'] ?? 'http://localhost:8000';
  final authToken = dotenv.env['AUTH_TOKEN'] ?? '';
  final headers = {'Authorization': 'Bearer $authToken'};

  // ── 「/parts/ready」ポーリング ──────────────────────
  const Duration pollInterval = kPollInterval;
  const int maxAttempts = kMaxAttempts;

  for (int i = 0; i < maxAttempts; i++) {
    final readyRes = await http.get(
      Uri.parse('$apiBase/api/$planId/parts/ready'),
      headers: headers, // Authorization
    );

    if (readyRes.statusCode == 200) {
      final ready = jsonDecode(readyRes.body) as Map;
      if (ready['ready'] == true) break; // 準備完了
    } else {
      throw Exception('準備確認失敗: ${readyRes.statusCode}');
    }

    // ── 準備未完了なら 30 秒待って再試行 ─────────────────
    if (i == maxAttempts - 1) {
      throw TimeoutException('部品準備がタイムアウトしました');
    }
    await Future.delayed(pollInterval); // ★ ← ここを変更
  }

  // ── 実データ取得 ──────────────────────────────────
  final res = await http.get(
    Uri.parse('$apiBase/api/$planId/parts'),
    headers: headers, // ★ Authorization
  );

  if (res.statusCode != 200) {
    throw Exception('部品一覧の取得に失敗: ${res.statusCode}');
  }

  if (res.statusCode == 200) {
    final body = res.body;

    if (kDebugMode) {
      final decoded = jsonDecode(body);
      final pretty = const JsonEncoder.withIndent('  ').convert(decoded);
      debugPrint('[DEBUG] parts レスポンス:\n$pretty');
    }
  }

  final List<dynamic> partsJson = jsonDecode(res.body);
  final int total = partsJson.length;

  _allParts = List.generate(partsJson.length, (i) {
    final item = partsJson[i] as Map<String, dynamic>;
    return Part(
      item['part_name'] as String,
      item['size'] as String,
      getVividColor(total, i),
    );
  });

  return _allParts!;
}

// 部品作成手順
Future<List<Map<String, dynamic>>> fetchPartsCreation(String planId) async {
  final apiBase = dotenv.env['API_BASE'] ?? 'http://localhost:8000';
  final authToken = dotenv.env['AUTH_TOKEN'] ?? '';
  final headers = {'Authorization': 'Bearer $authToken'};

  const int maxAttempts = kMaxAttempts;
  const Duration interval = kPollInterval;

  /* ── ① /parts_creation/ready をポーリング ─────────────────── */
  for (int i = 0; i < maxAttempts; i++) {
    final readyRes = await http.get(
      Uri.parse('$apiBase/api/$planId/parts_creation/ready'),
      headers: headers, // Authorization
    );

    if (readyRes.statusCode == 200) {
      final ready = jsonDecode(readyRes.body) as Map;
      if (ready['ready'] == true) break; // 準備完了
    } else {
      throw Exception('準備確認失敗: ${readyRes.statusCode}');
    }

    // ── 未完了なら 30 秒待機 ──────────────────────────
    if (i == maxAttempts - 1) {
      throw TimeoutException('部品作成手順の準備がタイムアウトしました');
    }
    await Future.delayed(interval); // ★ ここを変更
  }

  /* ── ② 実データ /parts_creation を取得 ───────────────────── */
  final res = await http.get(
    Uri.parse('$apiBase/api/$planId/parts_creation'),
    headers: headers, // ★ 認可ヘッダ
  );

  if (res.statusCode != 200) {
    throw Exception('部品作成手順の取得に失敗: ${res.statusCode}');
  }

  if (res.statusCode == 200) {
    final body = res.body;

    if (kDebugMode) {
      final decoded = jsonDecode(body);
      final pretty = const JsonEncoder.withIndent('  ').convert(decoded);
      debugPrint('[DEBUG] parts_creation レスポンス:\n$pretty');
    }
  }

  final list = jsonDecode(res.body) as List;
  final parts = list
      .map<Map<String, dynamic>>((e) => Map<String, dynamic>.from(e))
      .toList();
  return parts;
}

// 組立手順数
Future<int> fetchAssemblyProcedureCount(String planId) async {
  // .env から設定を取得
  final apiBase = dotenv.env['API_BASE'] ?? 'http://localhost:8000';
  final authToken = dotenv.env['AUTH_TOKEN'] ?? '';
  final headers = {'Authorization': 'Bearer $authToken'};

  const int maxAttempts = kMaxAttempts;
  const Duration pollInterval = kPollInterval;

  /* ── ① /assembly_parts/ready をポーリング ───────────────── */
  for (int i = 0; i < maxAttempts; i++) {
    final readyRes = await http.get(
      Uri.parse('$apiBase/api/$planId/assembly_parts/ready'),
      headers: headers, // Authorization: Bearer …
    );

    if (readyRes.statusCode == 200) {
      final ready = jsonDecode(readyRes.body) as Map;
      if (ready['ready'] == true) break; // 準備完了で抜ける
    } else {
      throw Exception('準備確認失敗: ${readyRes.statusCode}');
    }

    // ── 未完了なら 30 秒待機 ──────────────────────────
    if (i == maxAttempts - 1) {
      throw TimeoutException('組立手順の準備がタイムアウトしました');
    }
    await Future.delayed(pollInterval); // ★ ここを変更
  }

  /* ── ② 総ページ数を取得 ─────────────────────────────── */
  final res = await http.get(
    Uri.parse('$apiBase/api/$planId/assembly_parts/procedure_num'),
    headers: headers, // ★ 認可ヘッダ
  );

  if (res.statusCode != 200) {
    throw Exception('組立手順数の取得失敗: ${res.statusCode}');
  }

  if (res.statusCode == 200) {
    final body = res.body;

    if (kDebugMode) {
      final decoded = jsonDecode(body);
      final pretty = const JsonEncoder.withIndent('  ').convert(decoded);
      debugPrint('[DEBUG] assembly_parts レスポンス:\n$pretty');
    }
  }

  return (jsonDecode(res.body) as Map)['num'] as int;
}

// 指定手順のモデル
Future<Map<String, dynamic>> fetchAssemblyStepModel(
  String planId,
  int step,
) async {
  final apiBase = dotenv.env['API_BASE'] ?? 'http://localhost:8000';
  final authToken = dotenv.env['AUTH_TOKEN'] ?? '';
  final headers = {'Authorization': 'Bearer $authToken'};

  final res = await http.get(
    Uri.parse('$apiBase/api/$planId/assembly_parts/procedure/$step'),
    headers: headers, // ★ 認可ヘッダ
  );

  if (res.statusCode != 200) {
    throw Exception('組立手順$step の取得失敗: ${res.statusCode}');
  }
  if (res.statusCode == 200) {
    final body = res.body;

    if (kDebugMode) {
      final decoded = jsonDecode(body);
      final pretty = const JsonEncoder.withIndent('  ').convert(decoded);
      debugPrint('[DEBUG] assembly_parts_procedure レスポンス:\n$pretty');
    }
  }
  return jsonDecode(res.body) as Map<String, dynamic>;
}

//PDFダウンロード
Future<Uint8List> fetchManualPdf(String planId) async {
  final apiBase = dotenv.env['API_BASE'] ?? 'http://localhost:8000';
  final authTok = dotenv.env['AUTH_TOKEN'] ?? '';
  final headers = {
    'Authorization': 'Bearer $authTok',
    'Accept': 'application/pdf', // ← 追加
  };

  // ① ready ポーリング
  for (int i = 0; i < kMaxAttempts; i++) {
    final res = await http.get(
      Uri.parse('$apiBase/api/$planId/manual_pdf/ready'),
      headers: headers,
    );

    if (res.statusCode == 200) {
      if ((jsonDecode(res.body) as Map)['ready'] == true) break;
    } else if (res.statusCode == 404) {
      throw Exception('plan_id が存在しません');
    } else {
      throw Exception('PDF準備確認失敗: ${res.statusCode}');
    }

    if (i == kMaxAttempts - 1) {
      throw TimeoutException('PDF の準備がタイムアウトしました');
    }
    await Future.delayed(kPollInterval);
  }

  // ② PDF 取得
  final pdfRes = await http.get(
    Uri.parse('$apiBase/api/$planId/manual_pdf'),
    headers: headers,
  );

  if (pdfRes.statusCode == 200) {
    if (kDebugMode) {
      debugPrint('[DEBUG] manual_pdf 受信サイズ: ${pdfRes.bodyBytes.length} bytes');
    }
    return pdfRes.bodyBytes; // ← JSON デコードせずそのまま返す
  }
  throw Exception('PDF取得失敗: ${pdfRes.statusCode} ${pdfRes.reasonPhrase}');
}

// ------------------------------------------------------------------
// ▼ Utility
// ------------------------------------------------------------------
Future<Uint8List> fileToUint8List(html.File file) {
  final c = Completer<Uint8List>();
  final reader = html.FileReader();
  reader.readAsArrayBuffer(file);
  reader.onLoad.listen((_) {
    final r = reader.result;
    if (r is ByteBuffer)
      c.complete(r.asUint8List());
    else if (r is Uint8List)
      c.complete(r);
    else
      c.completeError('Unsupported type');
  });
  reader.onError.listen((e) => c.completeError('FileReader error: $e'));
  return c.future;
}

Color getVividColor(int divisions, int index) {
  final hue = (index % divisions) * (360 / divisions);
  return HSLColor.fromAHSL(1.0, hue, 0.9, 0.5).toColor();
}

// ------------------------------------------------------------------
// ▼ Model クラス
// ------------------------------------------------------------------
class Part {
  final String name;
  final String size;
  final Color color;
  Part(this.name, this.size, this.color);
}

// ------------------------------------------------------------------
// ▼ 共通 UI コンポーネント
// ------------------------------------------------------------------
class SectionCard extends StatelessWidget {
  const SectionCard({
    required this.title,
    required this.child,
    this.number,
    this.verticalMargin = 6, // ← ここでデフォルト余白を定義
    this.verticalPadding = 8, // ← 上側パディング
    this.bottomPadding = 12, // ← 下側パディング
    super.key,
  });

  final String title;
  final Widget child;
  final int? number;

  // ★ 追加した 3 つの余白プロパティ
  final double verticalMargin;
  final double verticalPadding;
  final double bottomPadding;

  @override
  Widget build(BuildContext context) {
    return Card(
      margin: EdgeInsets.symmetric(vertical: verticalMargin),
      shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(12)),
      elevation: 4,
      child: Padding(
        padding: EdgeInsets.fromLTRB(20, verticalPadding, 20, bottomPadding),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text(
              number != null ? '$number. $title' : title,
              style: Theme.of(context).textTheme.titleMedium!.copyWith(
                fontWeight: FontWeight.w700,
                color: number != null ? const Color(0xFF5566FF) : null,
              ),
            ),
            const SizedBox(height: 12), // タイトル下の余白
            child,
          ],
        ),
      ),
    );
  }
}

// ------------------------------------------------------------------
// ▼ メインページ
// ------------------------------------------------------------------
class MainPage extends StatefulWidget {
  const MainPage({super.key});
  @override
  State<MainPage> createState() => _MainPageState();
}

class _MainPageState extends State<MainPage> {
  late html.DivElement _dropArea;

  bool _showViewer = false;
  Future<List<Part>>? _partsFuture;
  List<Map<String, dynamic>> _partCreationSteps = [];
  int _currentStep = 0;
  int _assemblyTotalSteps = 0;
  final Map<int, Map<String, dynamic>> _stepCache = {};
  //デザイン
  static const _kViewerHelpText = '''
    右ドラッグ   : 回転
    ホイール     : ズーム
    ホイールドラッグ   : 平行移動
    ''';
  bool _readyToDownload = false;
  bool _isDownloading = false;
  //送信済みモデルの保持
  Map<String, dynamic>? _lastAssembled; // 完成モデル用
  Map<String, dynamic>? _lastStep; // 手順モデル用
  //ロード状態判定
  bool get _isAssembledLoading => _lastAssembled == null; // 完成モデル
  bool get _isStepLoading =>
      !_stepCache.containsKey(_currentStep + 1) || _lastStep == null; // 手順モデル
  @override
  void initState() {
    super.initState();

    // ドロップ用 DIV
    _dropArea = html.DivElement()
      ..style.width = '100%'
      ..style.height = '100%';

    _dropArea.onDragOver.listen((e) {
      e.preventDefault();
    });
    _dropArea.onDrop.listen((e) {
      e.preventDefault();
      final files = e.dataTransfer?.files;
      if (files != null && files.isNotEmpty) {
        setState(() {
          _droppedImageFile = files[0];
          _previewImageUrl = html.Url.createObjectUrl(_droppedImageFile);
        });
      }
    });

    // ignore: undefined_prefixed_name
    ui.platformViewRegistry.registerViewFactory(
      'drop-area',
      (int viewId) => _dropArea,
    );
    //3Dの再描画用
    html.window.onMessage.listen((event) {
      final data = event.data;
      if (data is Map && data['threeViewerReady'] == true) {
        final role = data['role']; // assembled / step どちらか
        final win = event.source; // EventTarget 型

        // postMessage を持つのは WindowBase
        if (win is html.WindowBase) {
          if (role == 'assembled' && _lastAssembled != null) {
            win.postMessage(_lastAssembled, '*');
          }
          if (role == 'step' && _lastStep != null) {
            win.postMessage(_lastStep, '*');
          }
        }
      }
    });
  }

  // ----------------------------------------------------------------
  // ▼ UI
  // ----------------------------------------------------------------
  @override
  Widget build(BuildContext context) {
    return Scaffold(
      body: Center(
        child: SingleChildScrollView(
          padding: const EdgeInsets.symmetric(vertical: 24, horizontal: 16),
          child: ConstrainedBox(
            constraints: const BoxConstraints(maxWidth: 1200), // 全体の横幅
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.stretch,
              children: [
                // タイトル
                Text(
                  'CraftMate AI',
                  style: Theme.of(context).textTheme.headlineSmall!.copyWith(
                    fontWeight: FontWeight.w700,
                  ),
                  textAlign: TextAlign.center,
                ),
                const SizedBox(height: 4),
                Text(
                  'AIが完成イメージ画像から必要となる部品や手順を検討し、手順書を作成します。',
                  style: Theme.of(context).textTheme.bodySmall,
                  textAlign: TextAlign.center,
                ),
                const SizedBox(height: 16),

                // 画像アップロード + 完成後イメージ（横並び）
                _buildTopSection(),

                const SizedBox(height: 8),

                if (_showViewer) ...[
                  const SizedBox(height: 12),

                  // 部品一覧 + 手順（横並び）
                  _buildPartsAndStepsSection(),

                  const SizedBox(height: 12),

                  // 組み立てステップビュー（縦で可視）
                  if (_assemblyTotalSteps > 0) _buildAssemblyStepViewer(),
                  const SizedBox(height: 16),
                  //ダウンロードボタン
                  if (_readyToDownload)
                    Align(
                      alignment: Alignment.center,
                      child: ElevatedButton.icon(
                        // ① アイコンを状況で切替
                        icon: _isDownloading
                            ? const SizedBox(
                                width: 16,
                                height: 16,
                                child: CircularProgressIndicator(
                                  strokeWidth: 2,
                                  valueColor: AlwaysStoppedAnimation<Color>(
                                    Colors.white,
                                  ),
                                ),
                              )
                            : const Icon(Icons.download),
                        // ② ラベルも切替
                        label: Text(_isDownloading ? 'ダウンロード中…' : '結果をダウンロード'),
                        // ③ 進行中は null で押下不可
                        onPressed: _isDownloading ? null : _onDownloadPressed,
                        style: ElevatedButton.styleFrom(
                          padding: const EdgeInsets.symmetric(
                            vertical: 14,
                            horizontal: 32,
                          ),
                        ),
                      ),
                    ),
                ],
              ],
            ),
          ),
        ),
      ),
    );
  }

  /// 画像アップロード ＋ 完成イメージ
  Widget _buildTopSection() {
    return LayoutBuilder(
      builder: (context, constraints) {
        final bool isNarrow = constraints.maxWidth < kBreakNarrow;

        Widget uploadCard = SectionCard(
          number: 1,
          title: '画像をアップロード',
          // ↓ 内側 LayoutBuilder で “左カードの幅” を取得
          child: LayoutBuilder(
            builder: (ctx, inner) {
              return Column(
                children: [
                  // inner.maxWidth が実幅
                  _buildImageDropAndPreview(isNarrow, inner.maxWidth),
                  const SizedBox(height: 16),
                  ElevatedButton(
                    onPressed: _onGeneratePressed,
                    child: const Text('組み立て手順を生成'),
                  ),
                ],
              );
            },
          ),
        );

        Widget? viewerCard = _showViewer
            ? _buildAssembledModelViewerSection()
            : null;

        if (isNarrow) {
          // --- Column ---
          return Column(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              uploadCard,
              if (viewerCard != null) ...[
                const SizedBox(height: 12),
                viewerCard,
              ],
            ],
          );
        } else {
          // --- Row ---
          return Row(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Expanded(
                child: SizedBox(height: _topCardHeight, child: uploadCard),
              ),
              if (viewerCard != null) ...[
                const SizedBox(width: 24),
                Expanded(
                  child: SizedBox(height: _topCardHeight, child: viewerCard),
                ),
              ],
            ],
          );
        }
      },
    );
  }

  /// ── 「部品一覧」＋「部品作成手順」 ──────────────────────────────
  Widget _buildPartsAndStepsSection() {
    return Row(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        /// 左 : 部品一覧
        Expanded(child: _buildPartList()),

        const SizedBox(width: 24),

        /// 右 : 部品作成手順
        Expanded(
          child: SectionCard(title: '部品作成手順', child: _buildPartCreationSteps()),
        ),
      ],
    );
  }

  //  組み立て手順ビュー（横幅で Row / Column を自動切替）
  Widget _buildAssemblyStepViewer() {
    final int total = _assemblyTotalSteps;
    final int stepNo = _currentStep + 1;
    final String desc = _stepCache[stepNo]?['description'] ?? '';

    return SectionCard(
      title: '組み立て手順',
      verticalPadding: 10,
      bottomPadding: 10,
      child: LayoutBuilder(
        builder: (context, constraints) {
          /* ----- 幅・高さを決定 ----- */
          final bool isWide = constraints.maxWidth >= kStepViewerBreak;
          final double vwRatio = isWide
              ? kStepViewerRowRatio
              : kStepViewerColRatio;
          final double viewerW = min(
            constraints.maxWidth * vwRatio,
            kStepViewerMaxWidth,
          );
          final double viewerH = viewerW / kStepViewerAspect;

          /* ----- 3D ビュー（hover で操作方法パネルを表示） ----- */
          final viewerBox = SizedBox(
            width: viewerW,
            height: viewerH,
            child: Container(
              decoration: _viewerDecoration,
              child: Stack(
                alignment: Alignment.center,
                children: [
                  const HtmlElementView(
                    viewType: 'step-three-iframe',
                    key: ValueKey('step-iframe'),
                  ),
                  if (_isStepLoading)
                    const CircularProgressIndicator(strokeWidth: 2),

                  // ── help icon ──
                  Positioned(top: 8, right: 8, child: buildHelpIcon()),
                ],
              ),
            ),
          );

          /* ----- ページ送り＋説明テキスト ----- */
          final rightPane = Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Row(
                mainAxisAlignment: MainAxisAlignment.end,
                children: [
                  IconButton(
                    icon: const Icon(Icons.chevron_left, size: 16),
                    padding: EdgeInsets.zero,
                    constraints: const BoxConstraints(
                      minWidth: 24,
                      minHeight: 24,
                    ),
                    splashRadius: 16,
                    visualDensity: const VisualDensity(
                      horizontal: -4,
                      vertical: -4,
                    ),
                    onPressed: _currentStep > 0
                        ? () => _loadAssemblyStep(_currentStep - 1)
                        : null,
                  ),
                  const SizedBox(width: 4),
                  Text(
                    '$stepNo / $total',
                    style: Theme.of(context).textTheme.bodySmall!.copyWith(
                      fontSize: 14,
                      letterSpacing: -0.5,
                    ),
                  ),
                  const SizedBox(width: 4),
                  IconButton(
                    icon: const Icon(Icons.chevron_right, size: 16),
                    padding: EdgeInsets.zero,
                    constraints: const BoxConstraints(
                      minWidth: 24,
                      minHeight: 24,
                    ),
                    splashRadius: 16,
                    visualDensity: const VisualDensity(
                      horizontal: -4,
                      vertical: -4,
                    ),
                    onPressed: _currentStep < total - 1
                        ? () => _loadAssemblyStep(_currentStep + 1)
                        : null,
                  ),
                ],
              ),
              const SizedBox(height: 6),
              Text(desc, style: Theme.of(context).textTheme.bodySmall),
            ],
          );

          /* ----- Row / Column 切替 ----- */
          return isWide
              ? Row(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    viewerBox,
                    const SizedBox(width: 16),
                    Expanded(child: rightPane),
                  ],
                )
              : Column(
                  crossAxisAlignment: CrossAxisAlignment.center,
                  children: [viewerBox, const SizedBox(height: 12), rightPane],
                );
        },
      ),
    );
  }

  /// ─────────────────────────────────────────────
  /// 小要素
  /// ─────────────────────────────────────────────
  // 画像D＆D
  // ▼ SubUI
  // ----------------------------------------------------------------
  // 画像ドロップ＆プレビュー
  Widget _buildImageDropAndPreview(bool isNarrow, double parentWidth) {
    const double kDropMax = 230.0; // ドロップ枠の最大幅
    const double kPreviewMax = 150.0; // プレビューの最大幅
    const double kGap = 16.0; // 行レイアウト時の間隔

    /* ----------- 幅を決定 ----------- */
    late double dropW, dropH, previewW;

    if (isNarrow) {
      // ======= Column レイアウト =======
      dropW = parentWidth * 0.8;
      dropH = dropW * 160 / 260;
      previewW = min(dropW * 0.6, kPreviewMax);
    } else {
      // ======= Row レイアウト =======
      const double totalMax = kDropMax + kGap + kPreviewMax + 20;
      final double scale =
          parentWidth <
              totalMax // はみ出す？
          ? parentWidth /
                totalMax // → 等比縮小
          : 1.0; // → そのまま

      dropW = kDropMax * scale;
      previewW = kPreviewMax * scale;
      dropH = dropW * 160 / 260; // 13:8 同比
    }

    /* ----------- ドロップ枠 ----------- */
    Widget drop = SizedBox(
      width: dropW,
      height: dropH,
      child: DottedBorder(
        dashPattern: const [6, 4],
        color: const Color(0xFF5566FF),
        strokeWidth: 1.2,
        borderType: BorderType.RRect,
        radius: const Radius.circular(12),
        child: Stack(
          alignment: Alignment.center,
          children: [
            const Icon(
              Icons.cloud_upload_outlined,
              size: 48,
              color: Color(0xFF5566FF),
            ),
            HtmlElementView(viewType: 'drop-area'),
          ],
        ),
      ),
    );

    /* ----------- プレビュー ----------- */
    Widget preview = SizedBox(
      width: previewW,
      height: previewW,
      child: Container(
        decoration: BoxDecoration(
          color: Colors.white,
          borderRadius: BorderRadius.circular(12),
          border: Border.all(color: Colors.black12),
        ),
        child: _previewImageUrl == null
            ? const Center(child: Text('Preview'))
            : ClipRRect(
                borderRadius: BorderRadius.circular(12),
                child: Image.network(_previewImageUrl!, fit: BoxFit.cover),
              ),
      ),
    );

    /* ----------- レイアウト ----------- */
    return isNarrow
        ? Column(
            crossAxisAlignment: CrossAxisAlignment.center,
            children: [drop, const SizedBox(height: 12), preview],
          )
        : Row(
            mainAxisAlignment: MainAxisAlignment.center,
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              drop,
              const SizedBox(width: kGap),
              preview,
            ],
          );
  }

  // 部品一覧
  Widget _buildPartList() {
    return SectionCard(
      title: '作成する部品一覧',
      child: FutureBuilder<List<Part>>(
        future: _partsFuture,
        builder: (context, snapshot) {
          if (snapshot.connectionState != ConnectionState.done) {
            return const Center(child: CircularProgressIndicator());
          }
          final parts = snapshot.data!;

          return LayoutBuilder(
            builder: (context, constraints) {
              const int columns = 2; // 列数を指定
              const double gap = 12;
              final double itemWidth =
                  (constraints.maxWidth - gap * (columns - 1)) / columns;

              return Wrap(
                spacing: gap,
                runSpacing: gap,
                children: [
                  for (final p in parts)
                    SizedBox(
                      width: itemWidth,
                      child: _PartTile(part: p),
                    ),
                ],
              );
            },
          );
        },
      ),
    );
  }

  // 部品作成手順
  Widget _buildPartCreationSteps() {
    if (_partCreationSteps.isEmpty) {
      // ---- ロード中 ----
      return const Center(child: CircularProgressIndicator());
    }

    return ListView.separated(
      shrinkWrap: true,
      physics: const NeverScrollableScrollPhysics(),
      itemCount: _partCreationSteps.length,
      separatorBuilder: (_, __) => const SizedBox(height: 6),
      itemBuilder: (context, i) {
        final step = _partCreationSteps[i];
        final rawNames = (step['part_name'] as String?) ?? '';
        // カンマ・全角カンマ・空白で分割 → トリム
        final parts = rawNames
            .split(RegExp(r'[,\s、]+'))
            .where((s) => s.isNotEmpty)
            .toList();

        return Container(
          padding: const EdgeInsets.all(12),
          decoration: BoxDecoration(
            color: const Color(0xFFF8FAFF),
            borderRadius: BorderRadius.circular(8),
            border: Border.all(color: Colors.black12),
          ),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              // ── 見出し（パーツ名チップを横並び Wrap）──────────
              Wrap(
                spacing: 6,
                runSpacing: 4,
                children: [
                  for (final name in parts)
                    Container(
                      padding: const EdgeInsets.symmetric(
                        vertical: 4,
                        horizontal: 8,
                      ),
                      decoration: BoxDecoration(
                        color: _partColor(name).withOpacity(.9),
                        borderRadius: BorderRadius.circular(6),
                      ),
                      child: Text(
                        name,
                        style: const TextStyle(
                          color: Colors.white,
                          fontSize: 12,
                          fontWeight: FontWeight.bold,
                        ),
                      ),
                    ),
                ],
              ),
              const SizedBox(height: 6),
              // ── description ────────────────────────────────
              Text(
                step['description'] as String? ?? '',
                style: Theme.of(context).textTheme.bodySmall,
              ),
            ],
          ),
        );
      },
    );
  }

  // 完成品3D ビュー
  Widget _buildAssembledModelViewerSection() {
    return SectionCard(
      title: '組み立て後のイメージ',
      child: Container(
        height: 240,
        decoration: _viewerDecoration,
        child: Stack(
          alignment: Alignment.center,
          children: [
            const HtmlElementView(
              viewType: 'three-iframe',
              key: ValueKey('assembled-iframe'),
            ),
            if (_isAssembledLoading)
              const CircularProgressIndicator(strokeWidth: 2),

            // ── help icon ──
            Positioned(top: 8, right: 8, child: buildHelpIcon()),
          ],
        ),
      ),
    );
  }

  //ダウンロードボタン
  Future<void> _onDownloadPressed() async {
    if (_planId == null) return;
    setState(() => _isDownloading = true);
    try {
      final bytes = await fetchManualPdf(_planId!);

      // ブラウザ保存
      final blob = html.Blob([bytes], 'application/pdf'); // ← MIME 型を明示
      final url = html.Url.createObjectUrlFromBlob(blob);

      final anchor = html.AnchorElement(href: url)
        ..download =
            'manual.pdf' // ← 拡張子を .pdf
        ..style.display = 'none';

      html.document.body!.append(anchor);
      anchor.click();
      anchor.remove();
      html.Url.revokeObjectUrl(url);
    } catch (e) {
      ScaffoldMessenger.of(
        context,
      ).showSnackBar(SnackBar(content: Text('ダウンロード失敗: $e')));
    } finally {
      // 終了時に必ずフラグを戻す
      if (mounted) setState(() => _isDownloading = false);
    }
  }

  // ----------------------------------------------------------------
  // ▼ イベントハンドラ
  // ----------------------------------------------------------------
  Future<void> _onGeneratePressed() async {
    if (_droppedImageFile == null) {
      ScaffoldMessenger.of(
        context,
      ).showSnackBar(const SnackBar(content: Text('画像を先にドロップしてください')));
      return;
    }
    try {
      final planId = await uploadImageToServer(_droppedImageFile!);
      setState(() {
        _planId = planId;
        _allParts = null;
        _partsFuture = fetchAllParts(planId);
        _showViewer = true;
      });

      // 組み立て済み OBJ
      final objText = await fetchAssembledModelOBJText(planId);
      final modelData = await fetchAssembledModelRenderDataFromOBJ(objText);

      await Future.delayed(const Duration(milliseconds: 300));
      // モデルデータを作ったら一旦保持
      setState(() {
        _pendingModelData = modelData;
        _lastAssembled = modelData;
      });

      // 既に iframe がロード済みなら即送信
      if (_iframeElement.contentWindow != null) {
        _iframeElement.contentWindow!.postMessage(modelData, '*');
        _pendingModelData = null;
      }

      // 部品作成手順
      final pcs = await fetchPartsCreation(planId);
      // 組立手順数
      final totalSteps = await fetchAssemblyProcedureCount(planId);

      setState(() {
        _partCreationSteps = pcs;
        _assemblyTotalSteps = totalSteps;
        _currentStep = 0;
      });

      await _loadAssemblyStep(0);
      setState(() {
        _readyToDownload = true; // ← ここでダウンロード解禁
      });
    } catch (e) {
      ScaffoldMessenger.of(
        context,
      ).showSnackBar(SnackBar(content: Text('生成失敗: $e')));
    }
  }

  // step 取得＆iframe へ送信
  Future<void> _loadAssemblyStep(int index) async {
    if (_planId == null) return;
    final stepNo = index + 1;
    if (!_stepCache.containsKey(stepNo)) {
      final raw = await fetchAssemblyStepModel(_planId!, stepNo);
      _stepCache[stepNo] = raw;
    }
    final data = _stepCache[stepNo]!;
    final objText = data['model'] as String;
    final modelMsg = await fetchAssembledModelRenderDataFromOBJ(objText);

    await Future.delayed(const Duration(milliseconds: 300));
    setState(() {
      _pendingStepData = modelMsg;
      _lastStep = modelMsg; // ← ここを setState 内に
    });

    /* iframe が既にロード済みならすぐ送信 */
    if (_stepIframeElement.contentWindow != null) {
      _stepIframeElement.contentWindow!.postMessage(modelMsg, '*');
      setState(() => _pendingModelData = null);
    }

    setState(() => _currentStep = index);
  }

  /// 部品名→カラーを取得（該当なしなら青紫を返す）
  Color _partColor(String name) {
    if (_allParts == null) return const Color(0xFF5566FF);
    final match = _allParts!.firstWhere(
      (p) => p.name == name,
      orElse: () => Part('', '', const Color(0xFF5566FF)),
    );
    return match.color;
  }

  Widget buildHelpIcon() {
    return PointerInterceptor(
      // ★ これを挟むだけ
      child: Tooltip(
        message: _kViewerHelpText,
        waitDuration: const Duration(milliseconds: 300),
        textStyle: const TextStyle(color: Colors.white, fontSize: 12),
        decoration: BoxDecoration(
          color: Colors.black.withOpacity(.85),
          borderRadius: BorderRadius.circular(6),
        ),
        child: const Icon(
          Icons.help_outline,
          size: 18,
          color: Colors.black54,
        ), // 見やすいアイコンに変更
      ),
    );
  }

  final _viewerDecoration = BoxDecoration(
    color: const Color(0xFFF8FAFF),
    borderRadius: BorderRadius.circular(8),
    border: Border.all(color: Colors.black12),
  );
}

//デザイン用
/// 1 つのタイルを分離（見た目は以前と同じ）
class _PartTile extends StatelessWidget {
  const _PartTile({required this.part});
  final Part part;

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.all(12),
      decoration: BoxDecoration(
        color: const Color(0xFFF8FAFF),
        borderRadius: BorderRadius.circular(8),
        border: Border.all(color: Colors.black12),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              Container(
                width: 14,
                height: 14,
                decoration: BoxDecoration(
                  color: part.color,
                  shape: BoxShape.circle,
                  border: Border.all(color: Colors.black12),
                ),
              ),
              const SizedBox(width: 6),
              Expanded(
                child: Text(
                  part.name,
                  style: const TextStyle(fontWeight: FontWeight.w600),
                  overflow: TextOverflow.ellipsis,
                ),
              ),
            ],
          ),
          const SizedBox(height: 6),
          Text(
            part.size,
            style: Theme.of(
              context,
            ).textTheme.bodySmall!.copyWith(color: Colors.black54),
          ),
        ],
      ),
    );
  }
}
