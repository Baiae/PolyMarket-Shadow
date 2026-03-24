// ── Enums ─────────────────────────────────────────────────────────────────────
/// Outcome of a prediction market trade or signal.
enum TradeOutcome { yes, no, unknown;
  static TradeOutcome fromString(String s) => switch (s.toUpperCase()) {
    'YES' => yes, 'NO' => no, _ => unknown };
  String get label => switch (this) {
    yes => 'YES', no => 'NO', unknown => '?' };
}

/// Paper/live order execution status.
enum OrderStatusEnum { paper, filled, killed, rateLimited, rejected, unknown;
  static OrderStatusEnum fromString(String s) => switch (s.toUpperCase()) {
    'PAPER'        => paper,
    'FILLED'       => filled,
    'KILLED'       => killed,
    'RATE_LIMITED' => rateLimited,
    'REJECTED'     => rejected,
    _              => unknown };
}

/// Source of a trading signal.
enum SignalSource { swarm, arb, unknown;
  static SignalSource fromString(String s) => switch (s.toUpperCase()) {
    'SWARM' => swarm, 'ARB' => arb, _ => unknown };
}

// Safe cast helpers — prevent runtime crashes on unexpected API shapes.
T? _cast<T>(dynamic value) => value is T ? value : null;
String _str(dynamic v, [String fallback = '']) =>
    _cast<String>(v) ?? fallback;
bool _bool(dynamic v, [bool fallback = false]) =>
    _cast<bool>(v) ?? fallback;
int _int(dynamic v, [int fallback = 0]) =>
    v is int ? v : (v is num ? v.toInt() : fallback);
double _dbl(dynamic v, [double fallback = 0.0]) =>
    v is num ? v.toDouble() : fallback;
DateTime _dt(dynamic v) {
  if (v is String && v.isNotEmpty) {
    return DateTime.tryParse(v) ?? DateTime.fromMillisecondsSinceEpoch(0);
  }
  return DateTime.fromMillisecondsSinceEpoch(0);
}

// ── Models ────────────────────────────────────────────────────────────────────

class HealthStatus {
  final String status;
  final DateTime timestamp;
  final bool paperTrading;
  final String version;

  const HealthStatus({required this.status, required this.timestamp,
      required this.paperTrading, this.version = '0.1.0'});

  factory HealthStatus.fromJson(Map<String, dynamic> j) => HealthStatus(
      status: _str(j['status'], 'unknown'),
      timestamp: _dt(j['timestamp']),
      paperTrading: _bool(j['paper_trading'], true),
      version: _str(j['version'], '0.1.0'));
}

class AgentStatus {
  final bool running;
  final bool killSwitchActive;
  final String killReason;
  final bool paperTrading;
  final Map<String, dynamic> riskStats;
  final int queueDepth;

  const AgentStatus({required this.running, required this.killSwitchActive,
      required this.killReason, required this.paperTrading,
      required this.riskStats, required this.queueDepth});

  factory AgentStatus.fromJson(Map<String, dynamic> j) {
    final raw = j['risk_stats'];
    final stats = (raw is Map)
        ? Map<String, dynamic>.from(raw) : <String, dynamic>{};
    return AgentStatus(
        running: _bool(j['running']),
        killSwitchActive: _bool(j['kill_switch_active']),
        killReason: _str(j['kill_reason']),
        paperTrading: _bool(j['paper_trading'], true),
        riskStats: stats,
        queueDepth: _int(j['queue_depth']));
  }
}

class TradeItem {
  final String marketId;
  final String question;
  final String outcome;
  /// Typed enum — use this in UI instead of raw string comparisons.
  final TradeOutcome outcomeEnum;
  final double amountUsd;
  final double price;
  final DateTime timestamp;
  final String category;

  const TradeItem({required this.marketId, required this.question,
      required this.outcome, required this.outcomeEnum,
      required this.amountUsd, required this.price,
      required this.timestamp, required this.category});

  factory TradeItem.fromJson(Map<String, dynamic> j) {
    final raw = _str(j['outcome']);
    return TradeItem(
        marketId: _str(j['market_id']),
        question: _str(j['question']),
        outcome: raw,
        outcomeEnum: TradeOutcome.fromString(raw),
        amountUsd: _dbl(j['amount_usd']),
        price: _dbl(j['price']),
        timestamp: _dt(j['timestamp']),
        category: _str(j['category']));
  }
}

class SignalItem {
  final String marketId;
  final String question;
  final String source;
  final SignalSource sourceEnum;
  final String consensus;
  final double confidence;
  final int yesCount;
  final int noCount;
  final DateTime timestamp;

  const SignalItem({required this.marketId, required this.question,
      required this.source, required this.sourceEnum,
      required this.consensus, required this.confidence,
      required this.yesCount, required this.noCount,
      required this.timestamp});

  factory SignalItem.fromJson(Map<String, dynamic> j) {
    final rawSource = _str(j['source']);
    return SignalItem(
        marketId: _str(j['market_id']),
        question: _str(j['question']),
        source: rawSource,
        sourceEnum: SignalSource.fromString(rawSource),
        consensus: _str(j['consensus']),
        confidence: _dbl(j['confidence']),
        yesCount: _int(j['yes_count']),
        noCount: _int(j['no_count']),
        timestamp: _dt(j['timestamp']));
  }
}

class OrderItem {
  final String marketId;
  final String question;
  final String side;
  final TradeOutcome sideEnum;
  final double sizeUsd;
  final double price;
  final String status;
  final OrderStatusEnum statusEnum;
  final String source;
  final SignalSource sourceEnum;
  final DateTime timestamp;

  const OrderItem({required this.marketId, required this.question,
      required this.side, required this.sideEnum,
      required this.sizeUsd, required this.price,
      required this.status, required this.statusEnum,
      required this.source, required this.sourceEnum,
      required this.timestamp});

  factory OrderItem.fromJson(Map<String, dynamic> j) {
    final rawSide   = _str(j['side']);
    final rawStatus = _str(j['status']);
    final rawSource = _str(j['source']);
    return OrderItem(
        marketId: _str(j['market_id']),
        question: _str(j['question']),
        side: rawSide,
        sideEnum: TradeOutcome.fromString(rawSide),
        sizeUsd: _dbl(j['size_usd']),
        price: _dbl(j['price']),
        status: rawStatus,
        statusEnum: OrderStatusEnum.fromString(rawStatus),
        source: rawSource,
        sourceEnum: SignalSource.fromString(rawSource),
        timestamp: _dt(j['timestamp']));
  }
}
