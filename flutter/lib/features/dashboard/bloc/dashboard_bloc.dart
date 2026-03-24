import 'dart:async';
import 'package:dio/dio.dart';
import 'package:flutter_bloc/flutter_bloc.dart';
import 'package:equatable/equatable.dart';
import '../../../core/api/agent_api.dart';
import '../../../core/models/agent_models.dart';

// ── Events ────────────────────────────────────────────────────────────────────
abstract class DashboardEvent extends Equatable {
  const DashboardEvent();
  @override List<Object?> get props => [];
}
class DashboardRefreshRequested extends DashboardEvent {}
/// Fired by the UI kill button — BLoC sets showKillConfirmation=true.
class DashboardKillButtonPressed extends DashboardEvent {}
/// Fired after the user confirms the dialog — BLoC triggers the API call.
class DashboardKillSwitchTriggered extends DashboardEvent {}
/// Fired when the user cancels the dialog.
class DashboardKillCancelled extends DashboardEvent {}
class DashboardResumeRequested extends DashboardEvent {}

// ── State ─────────────────────────────────────────────────────────────────────
enum DashboardStatus { initial, loading, success, failure }

class DashboardState extends Equatable {
  const DashboardState({
    this.status = DashboardStatus.initial,
    this.agentStatus, this.health,
    this.errorMessage = '',
    this.killActionInProgress = false,
    this.showKillConfirmation = false,
    this.lastUpdated,
  });
  final DashboardStatus status;
  final AgentStatus? agentStatus;
  final HealthStatus? health;
  final String errorMessage;
  final bool killActionInProgress;
  /// When true the UI should show the kill-switch confirmation dialog.
  final bool showKillConfirmation;
  /// Timestamp of last successful refresh — shown in UI as stale indicator.
  final DateTime? lastUpdated;

  DashboardState copyWith({
    DashboardStatus? status, AgentStatus? agentStatus,
    HealthStatus? health, String? errorMessage,
    bool? killActionInProgress, bool? showKillConfirmation,
    DateTime? lastUpdated,
  }) => DashboardState(
    status: status ?? this.status,
    agentStatus: agentStatus ?? this.agentStatus,
    health: health ?? this.health,
    errorMessage: errorMessage ?? this.errorMessage,
    killActionInProgress: killActionInProgress ?? this.killActionInProgress,
    showKillConfirmation: showKillConfirmation ?? this.showKillConfirmation,
    lastUpdated: lastUpdated ?? this.lastUpdated,
  );

  @override
  List<Object?> get props => [
    status, agentStatus, health, errorMessage,
    killActionInProgress, showKillConfirmation, lastUpdated,
  ];
}

// ── BLoC ──────────────────────────────────────────────────────────────────────
class DashboardBloc extends Bloc<DashboardEvent, DashboardState> {
  static const _refreshInterval = Duration(seconds: 5);

  DashboardBloc(this._api) : super(const DashboardState()) {
    on<DashboardRefreshRequested>(_onRefresh);
    on<DashboardKillButtonPressed>(_onKillButtonPressed);
    on<DashboardKillSwitchTriggered>(_onKillConfirmed);
    on<DashboardKillCancelled>(_onKillCancelled);
    on<DashboardResumeRequested>(_onResume);
    _timer = Timer.periodic(_refreshInterval,
        (_) => add(DashboardRefreshRequested()));
    add(DashboardRefreshRequested());
  }
  final AgentApi _api;
  Timer? _timer;

  Future<void> _onRefresh(
      DashboardRefreshRequested e, Emitter<DashboardState> emit) async {
    // Only show spinner on first load; background refreshes stay silent.
    if (state.agentStatus == null) {
      emit(state.copyWith(status: DashboardStatus.loading));
    }
    try {
      final results = await Future.wait([_api.getHealth(), _api.getStatus()]);
      emit(state.copyWith(
        status: DashboardStatus.success,
        health: results[0] as HealthStatus,
        agentStatus: results[1] as AgentStatus,
        lastUpdated: DateTime.now(),
      ));
    } on DioException catch (e) {
      // Surface the friendly message set by ApiInterceptor.
      final msg = e.message ?? 'Cannot reach agent. Is it running?';
      if (state.agentStatus == null) {
        emit(state.copyWith(status: DashboardStatus.failure, errorMessage: msg));
      }
    } on Exception {
      if (state.agentStatus == null) {
        emit(state.copyWith(
          status: DashboardStatus.failure,
          errorMessage: 'Cannot reach agent. Is it running?',
        ));
      }
    }
  }

  void _onKillButtonPressed(
      DashboardKillButtonPressed e, Emitter<DashboardState> emit) {
    emit(state.copyWith(showKillConfirmation: true));
  }

  void _onKillCancelled(
      DashboardKillCancelled e, Emitter<DashboardState> emit) {
    emit(state.copyWith(showKillConfirmation: false));
  }

  Future<void> _onKillConfirmed(
      DashboardKillSwitchTriggered e, Emitter<DashboardState> emit) async {
    emit(state.copyWith(showKillConfirmation: false, killActionInProgress: true));
    try {
      await _api.triggerKillSwitch();
      add(DashboardRefreshRequested());
    } on Exception {
      emit(state.copyWith(
        errorMessage: 'Failed to activate kill switch. Try again.',
      ));
    } finally {
      emit(state.copyWith(killActionInProgress: false));
    }
  }

  Future<void> _onResume(
      DashboardResumeRequested e, Emitter<DashboardState> emit) async {
    emit(state.copyWith(killActionInProgress: true));
    try {
      await _api.resumeTrading();
      add(DashboardRefreshRequested());
    } on Exception {
      emit(state.copyWith(errorMessage: 'Failed to resume. Try again.'));
    } finally {
      emit(state.copyWith(killActionInProgress: false));
    }
  }

  @override
  Future<void> close() {
    _timer?.cancel();
    return super.close();
  }
}
