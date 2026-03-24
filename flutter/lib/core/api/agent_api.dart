import 'package:dio/dio.dart';
import 'package:flutter/foundation.dart';
import '../models/agent_models.dart';
import 'api_interceptor.dart';

class AgentApi {
  AgentApi({String? baseUrl}) : _dio = _buildDio(baseUrl);

  final Dio _dio;

  static Dio _buildDio(String? baseUrl) {
    const envUrl = String.fromEnvironment('API_BASE_URL');
    final resolvedUrl = baseUrl ?? (envUrl.isNotEmpty ? envUrl : null);

    // Warn in debug if falling back to localhost — fails on real devices.
    if (resolvedUrl == null && kDebugMode) {
      debugPrint(
        '[AgentApi] WARNING: No API_BASE_URL set. '
        'Defaulting to localhost — will fail on a physical device. '
        'Pass --dart-define=API_BASE_URL=<codespaces-url> when running.',
      );
    }

    final dio = Dio(BaseOptions(
      baseUrl: resolvedUrl ?? 'http://localhost:8000/api',
      connectTimeout: const Duration(seconds: 10),
      receiveTimeout: const Duration(seconds: 10),
    ));
    dio.interceptors.add(ApiInterceptor());
    return dio;
  }

  Future<HealthStatus> getHealth() async {
    final res = await _dio.get<Map<String, dynamic>>('/healthz');
    return HealthStatus.fromJson(res.data!);
  }

  Future<AgentStatus> getStatus() async {
    final res = await _dio.get<Map<String, dynamic>>('/status');
    return AgentStatus.fromJson(res.data!);
  }

  Future<List<TradeItem>> getTrades({int limit = 50}) async {
    final res = await _dio.get<List<dynamic>>('/trades',
        queryParameters: {'limit': limit});
    return (res.data as List)
        .map((e) => TradeItem.fromJson(e as Map<String, dynamic>))
        .toList();
  }

  Future<List<SignalItem>> getSignals({int limit = 50}) async {
    final res = await _dio.get<List<dynamic>>('/signals',
        queryParameters: {'limit': limit});
    return (res.data as List)
        .map((e) => SignalItem.fromJson(e as Map<String, dynamic>))
        .toList();
  }

  Future<List<OrderItem>> getPositions({int limit = 100}) async {
    final res = await _dio.get<List<dynamic>>('/positions',
        queryParameters: {'limit': limit});
    return (res.data as List)
        .map((e) => OrderItem.fromJson(e as Map<String, dynamic>))
        .toList();
  }

  Future<bool> triggerKillSwitch() async {
    final res = await _dio.post<Map<String, dynamic>>('/kill');
    return res.data?['success'] as bool? ?? false;
  }

  Future<bool> resumeTrading() async {
    final res = await _dio.post<Map<String, dynamic>>('/resume');
    return res.data?['success'] as bool? ?? false;
  }
}
