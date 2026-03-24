import 'package:dio/dio.dart';

/// Central Dio interceptor — handles all API errors in one place.
/// Each BLoC only catches the re-thrown [ApiException] and maps it to
/// a friendly message via [ApiException.friendly].
class ApiInterceptor extends Interceptor {
  @override
  void onError(DioException err, ErrorInterceptorHandler handler) {
    final friendly = _toFriendly(err);
    handler.next(err.copyWith(message: friendly));
  }

  String _toFriendly(DioException err) {
    switch (err.type) {
      case DioExceptionType.connectionTimeout:
      case DioExceptionType.receiveTimeout:
      case DioExceptionType.sendTimeout:
        return 'Connection timed out — is the agent running?';
      case DioExceptionType.connectionError:
        return 'Cannot reach agent. Check the API URL and network.';
      case DioExceptionType.badResponse:
        final code = err.response?.statusCode;
        if (code == 401) return 'Unauthorised — check your credentials.';
        if (code == 429) return 'Rate limited — too many requests.';
        if (code != null && code >= 500) return 'Agent server error ($code).';
        return 'Unexpected response from agent (${code ?? '?'}).';
      default:
        return 'Network error — ${err.message ?? 'unknown'}';
    }
  }
}
