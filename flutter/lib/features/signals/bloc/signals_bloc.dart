import 'dart:async';
import 'package:dio/dio.dart';
import 'package:flutter_bloc/flutter_bloc.dart';
import 'package:equatable/equatable.dart';
import '../../../core/api/agent_api.dart';
import '../../../core/models/agent_models.dart';

abstract class SignalsEvent extends Equatable {
  const SignalsEvent();
  @override List<Object?> get props => [];
}
class SignalsRefreshRequested extends SignalsEvent {}

enum SignalsStatus { initial, loading, success, failure }

class SignalsState extends Equatable {
  const SignalsState({
    this.status = SignalsStatus.initial,
    this.signals = const [],
    this.positions = const [],
    this.errorMessage = '',
    this.lastUpdated,
  });
  final SignalsStatus status;
  final List<SignalItem> signals;
  final List<OrderItem> positions;
  final String errorMessage;
  final DateTime? lastUpdated;

  SignalsState copyWith({SignalsStatus? status, List<SignalItem>? signals,
      List<OrderItem>? positions, String? errorMessage,
      DateTime? lastUpdated}) => SignalsState(
      status: status ?? this.status,
      signals: signals ?? this.signals,
      positions: positions ?? this.positions,
      errorMessage: errorMessage ?? this.errorMessage,
      lastUpdated: lastUpdated ?? this.lastUpdated);

  @override
  List<Object?> get props =>
      [status, signals, positions, errorMessage, lastUpdated];
}

class SignalsBloc extends Bloc<SignalsEvent, SignalsState> {
  static const _refreshInterval = Duration(seconds: 10);
  static const _maxBackoff = Duration(seconds: 60);

  SignalsBloc(this._api) : super(const SignalsState()) {
    on<SignalsRefreshRequested>(_onRefresh);
    _scheduleTimer(_refreshInterval);
    add(SignalsRefreshRequested());
  }

  final AgentApi _api;
  Timer? _timer;
  int _failureCount = 0;

  void _scheduleTimer(Duration interval) {
    _timer?.cancel();
    _timer = Timer.periodic(interval, (_) => add(SignalsRefreshRequested()));
  }

  Future<void> _onRefresh(
      SignalsRefreshRequested e, Emitter<SignalsState> emit) async {
    if (state.lastUpdated == null) {
      emit(state.copyWith(status: SignalsStatus.loading));
    }
    try {
      final results = await Future.wait([
        _api.getSignals(limit: 50),
        _api.getPositions(limit: 100),
      ]);
      _failureCount = 0;
      _scheduleTimer(_refreshInterval);
      emit(state.copyWith(
          status: SignalsStatus.success,
          signals: results[0] as List<SignalItem>,
          positions: results[1] as List<OrderItem>,
          lastUpdated: DateTime.now()));
    } on DioException catch (e) {
      _handleFailure(emit, e.message ?? 'Could not load signals.');
    } on Exception {
      _handleFailure(emit, 'Could not load signals. Retrying…');
    }
  }

  void _handleFailure(Emitter<SignalsState> emit, String message) {
    _failureCount++;
    final backoff = Duration(
        seconds: (_refreshInterval.inSeconds * (1 << (_failureCount - 1)))
            .clamp(0, _maxBackoff.inSeconds));
    _scheduleTimer(backoff);
    if (state.lastUpdated == null) {
      emit(state.copyWith(
          status: SignalsStatus.failure, errorMessage: message));
    }
  }

  @override
  Future<void> close() { _timer?.cancel(); return super.close(); }
}
