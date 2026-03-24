import 'dart:async';
import 'package:dio/dio.dart';
import 'package:flutter_bloc/flutter_bloc.dart';
import 'package:equatable/equatable.dart';
import '../../../core/api/agent_api.dart';
import '../../../core/models/agent_models.dart';

abstract class TradesEvent extends Equatable {
  const TradesEvent();
  @override List<Object?> get props => [];
}
class TradesRefreshRequested extends TradesEvent {}

enum TradesStatus { initial, loading, success, failure }

class TradesState extends Equatable {
  const TradesState({
    this.status = TradesStatus.initial,
    this.trades = const [],
    this.errorMessage = '',
    this.lastUpdated,
  });
  final TradesStatus status;
  final List<TradeItem> trades;
  final String errorMessage;
  /// Null until first successful fetch — shown in UI as stale indicator.
  final DateTime? lastUpdated;

  TradesState copyWith({TradesStatus? status, List<TradeItem>? trades,
      String? errorMessage, DateTime? lastUpdated}) => TradesState(
      status: status ?? this.status,
      trades: trades ?? this.trades,
      errorMessage: errorMessage ?? this.errorMessage,
      lastUpdated: lastUpdated ?? this.lastUpdated);

  @override List<Object?> get props =>
      [status, trades, errorMessage, lastUpdated];
}

class TradesBloc extends Bloc<TradesEvent, TradesState> {
  /// Named constant — easy to tweak without hunting through code.
  static const _refreshInterval = Duration(seconds: 8);
  static const _maxBackoff = Duration(seconds: 60);

  TradesBloc(this._api) : super(const TradesState()) {
    on<TradesRefreshRequested>(_onRefresh);
    _scheduleTimer(_refreshInterval);
    add(TradesRefreshRequested());
  }

  final AgentApi _api;
  Timer? _timer;
  int _failureCount = 0;

  void _scheduleTimer(Duration interval) {
    _timer?.cancel();
    _timer = Timer.periodic(interval, (_) => add(TradesRefreshRequested()));
  }

  Future<void> _onRefresh(
      TradesRefreshRequested e, Emitter<TradesState> emit) async {
    // Show spinner only on the very first load.
    if (state.lastUpdated == null) {
      emit(state.copyWith(status: TradesStatus.loading));
    }
    try {
      final trades = await _api.getTrades(limit: 100);
      _failureCount = 0;
      _scheduleTimer(_refreshInterval);   // restore normal cadence on success
      emit(state.copyWith(
          status: TradesStatus.success,
          trades: trades,
          lastUpdated: DateTime.now()));
    } on DioException catch (e) {
      _handleFailure(emit, e.message ?? 'Could not load whale trades.');
    } on Exception {
      _handleFailure(emit, 'Could not load whale trades. Retrying…');
    }
  }

  void _handleFailure(Emitter<TradesState> emit, String message) {
    _failureCount++;
    // Exponential backoff: 8s, 16s, 32s, 60s (capped).
    final backoff = Duration(
        seconds: (_refreshInterval.inSeconds * (1 << (_failureCount - 1)))
            .clamp(0, _maxBackoff.inSeconds));
    _scheduleTimer(backoff);
    // Only replace UI if there's no prior data to show.
    if (state.lastUpdated == null) {
      emit(state.copyWith(status: TradesStatus.failure, errorMessage: message));
    }
  }

  @override
  Future<void> close() { _timer?.cancel(); return super.close(); }
}
