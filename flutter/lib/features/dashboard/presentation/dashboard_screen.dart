import 'package:flutter/material.dart';
import 'package:flutter_bloc/flutter_bloc.dart';
import '../../../core/models/agent_models.dart';
import '../bloc/dashboard_bloc.dart';

class DashboardScreen extends StatelessWidget {
  const DashboardScreen({super.key});
  @override
  // BLoC is provided by MultiBlocProvider in HomeScreen — no local provider needed.
  Widget build(BuildContext context) => const _DashboardView();
}

class _DashboardView extends StatelessWidget {
  const _DashboardView();

  @override
  Widget build(BuildContext context) {
    return BlocListener<DashboardBloc, DashboardState>(
      // UI responds to BLoC-driven confirmation flag — no logic in view.
      listenWhen: (prev, curr) =>
          curr.showKillConfirmation && !prev.showKillConfirmation,
      listener: (context, state) => _showKillDialog(context),
      child: Scaffold(
        appBar: AppBar(
          title: const Text('Poly-Shadow'),
          actions: [IconButton(
            icon: const Icon(Icons.refresh),
            onPressed: () => context
                .read<DashboardBloc>().add(DashboardRefreshRequested()),
          )],
        ),
        body: BlocBuilder<DashboardBloc, DashboardState>(
          builder: (context, state) {
            if (state.status == DashboardStatus.failure)
              return _ErrorCard(
                message: state.errorMessage,
                onRetry: () => context
                    .read<DashboardBloc>().add(DashboardRefreshRequested()),
              );
            if (state.agentStatus == null)
              return const _SkeletonLoader();
            final s = state.agentStatus!;
            return RefreshIndicator(
              onRefresh: () async => context
                  .read<DashboardBloc>().add(DashboardRefreshRequested()),
              child: ListView(padding: const EdgeInsets.all(16), children: [
                if (s.killSwitchActive)
                  _KillBanner(onResume: () => context
                      .read<DashboardBloc>().add(DashboardResumeRequested())),
                _StatusCard(status: s, health: state.health),
                const SizedBox(height: 12),
                _RiskCard(stats: s.riskStats),
                const SizedBox(height: 12),
                if (!s.killSwitchActive)
                  _KillButton(
                    inProgress: state.killActionInProgress,
                    // Dispatches event — BLoC owns the confirmation logic.
                    onPressed: () => context
                        .read<DashboardBloc>().add(DashboardKillButtonPressed()),
                  ),
              ]),
            );
          },
        ),
      ),
    );
  }

  Future<void> _showKillDialog(BuildContext context) async {
    final confirmed = await showDialog<bool>(
      context: context,
      builder: (_) => AlertDialog(
        title: const Text('Activate Kill Switch?'),
        content: const Text('This halts all trading. You can resume manually.'),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(context, false),
            child: const Text('Cancel'),
          ),
          FilledButton(
            style: FilledButton.styleFrom(backgroundColor: Colors.red),
            onPressed: () => Navigator.pop(context, true),
            child: const Text('KILL'),
          ),
        ],
      ),
    );
    if (!context.mounted) return;
    if (confirmed == true) {
      context.read<DashboardBloc>().add(DashboardKillSwitchTriggered());
    } else {
      context.read<DashboardBloc>().add(DashboardKillCancelled());
    }
  }
}

// ── Skeleton loader (shown while first data loads) ────────────────────────────
class _SkeletonLoader extends StatefulWidget {
  const _SkeletonLoader();
  @override
  State<_SkeletonLoader> createState() => _SkeletonLoaderState();
}

class _SkeletonLoaderState extends State<_SkeletonLoader>
    with SingleTickerProviderStateMixin {
  late final AnimationController _ctrl;
  late final Animation<double> _anim;

  @override
  void initState() {
    super.initState();
    _ctrl = AnimationController(
        vsync: this, duration: const Duration(milliseconds: 900))
      ..repeat(reverse: true);
    _anim = Tween<double>(begin: 0.3, end: 0.7).animate(_ctrl);
  }

  @override
  void dispose() { _ctrl.dispose(); super.dispose(); }

  @override
  Widget build(BuildContext context) {
    return AnimatedBuilder(
      animation: _anim,
      builder: (_, __) => ListView(padding: const EdgeInsets.all(16), children: [
        _SkeletonCard(height: 100, opacity: _anim.value),
        const SizedBox(height: 12),
        _SkeletonCard(height: 160, opacity: _anim.value),
        const SizedBox(height: 12),
        _SkeletonCard(height: 52, opacity: _anim.value),
      ]),
    );
  }
}

class _SkeletonCard extends StatelessWidget {
  const _SkeletonCard({required this.height, required this.opacity});
  final double height;
  final double opacity;
  @override
  Widget build(BuildContext context) => Opacity(
      opacity: opacity,
      child: Card(child: SizedBox(height: height)));
}

// ── Remaining widgets ─────────────────────────────────────────────────────────

class _KillBanner extends StatelessWidget {
  const _KillBanner({required this.onResume});
  final VoidCallback onResume;
  @override
  Widget build(BuildContext context) => Card(
      color: Colors.red.shade700,
      margin: const EdgeInsets.only(bottom: 12),
      child: Padding(padding: const EdgeInsets.all(12),
        child: Row(children: [
          const Icon(Icons.dangerous, color: Colors.white, size: 32),
          const SizedBox(width: 12),
          const Expanded(child: Column(
              crossAxisAlignment: CrossAxisAlignment.start, children: [
            Text('KILL SWITCH ACTIVE', style: TextStyle(color: Colors.white,
                fontWeight: FontWeight.bold, fontSize: 16)),
            Text('All trading halted.',
                style: TextStyle(color: Colors.white70)),
          ])),
          FilledButton(
            style: FilledButton.styleFrom(backgroundColor: Colors.white),
            onPressed: onResume,
            child: Text('Resume',
                style: TextStyle(color: Colors.red.shade700)),
          ),
        ])));
}

class _StatusCard extends StatelessWidget {
  const _StatusCard({required this.status, required this.health});
  final AgentStatus status;
  final HealthStatus? health;
  @override
  Widget build(BuildContext context) => Card(
      child: Padding(padding: const EdgeInsets.all(16),
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Row(children: [
            Icon(Icons.circle, size: 12,
                color: status.running ? Colors.green : Colors.orange),
            const SizedBox(width: 8),
            Text(status.running ? 'Agent Running' : 'Agent Idle',
                style: Theme.of(context).textTheme.titleMedium),
            const Spacer(),
            Chip(
              label: Text(status.paperTrading ? '📋 PAPER' : '🔴 LIVE',
                  style: const TextStyle(fontSize: 12)),
              backgroundColor: status.paperTrading
                  ? Colors.blue.shade100 : Colors.red.shade100,
            ),
          ]),
          const Divider(height: 20),
          _Row('Queue depth', '${status.queueDepth} markets'),
          _Row('API status', health?.status ?? '—'),
          _Row('Version', health?.version ?? '—'),
        ])));
}

class _RiskCard extends StatelessWidget {
  const _RiskCard({required this.stats});
  final Map<String, dynamic> stats;
  @override
  Widget build(BuildContext context) {
    final drawdown = (stats['drawdown_pct'] as num?)?.toDouble() ?? 0;
    final dc = drawdown > 20 ? Colors.red
        : drawdown > 10 ? Colors.orange : Colors.green;
    return Card(child: Padding(padding: const EdgeInsets.all(16),
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Text('Risk', style: Theme.of(context).textTheme.titleMedium),
          const Divider(height: 20),
          _Row('Bankroll',
              '\$${(stats['current_bankroll'] as num?)?.toStringAsFixed(2) ?? '—'}'),
          _Row('Peak',
              '\$${(stats['peak_bankroll'] as num?)?.toStringAsFixed(2) ?? '—'}'),
          _Row('Return',
              '${(stats['total_return_pct'] as num?)?.toStringAsFixed(1) ?? '0'}%'),
          Row(children: [
            const Text('Drawdown', style: TextStyle(color: Colors.grey)),
            const Spacer(),
            Text('${drawdown.toStringAsFixed(1)}%',
                style: TextStyle(color: dc, fontWeight: FontWeight.bold)),
          ]),
          const SizedBox(height: 8),
          ClipRRect(borderRadius: BorderRadius.circular(4),
            child: LinearProgressIndicator(value: drawdown / 100,
                backgroundColor: Colors.grey.shade200,
                color: dc, minHeight: 8)),
          const SizedBox(height: 4),
          Text('Kill switch fires at 30%',
              style: TextStyle(fontSize: 11, color: Colors.grey.shade500)),
        ])));
  }
}

class _KillButton extends StatelessWidget {
  const _KillButton({required this.inProgress, required this.onPressed});
  final bool inProgress;
  final VoidCallback onPressed;
  @override
  Widget build(BuildContext context) => SizedBox(
      width: double.infinity,
      child: FilledButton.icon(
        style: FilledButton.styleFrom(backgroundColor: Colors.red.shade700,
            padding: const EdgeInsets.symmetric(vertical: 16)),
        onPressed: inProgress ? null : onPressed,
        icon: inProgress
            ? const SizedBox(width: 16, height: 16,
                child: CircularProgressIndicator(
                    color: Colors.white, strokeWidth: 2))
            : const Icon(Icons.stop_circle_outlined),
        label: const Text('Activate Kill Switch',
            style: TextStyle(fontSize: 16)),
      ));
}

class _Row extends StatelessWidget {
  const _Row(this.label, this.value);
  final String label;
  final String value;
  @override
  Widget build(BuildContext context) => Padding(
      padding: const EdgeInsets.symmetric(vertical: 3),
      child: Row(children: [
        Text(label, style: const TextStyle(color: Colors.grey)),
        const Spacer(),
        Text(value, style: const TextStyle(fontWeight: FontWeight.w500)),
      ]));
}

class _ErrorCard extends StatelessWidget {
  const _ErrorCard({required this.message, required this.onRetry});
  final String message;
  final VoidCallback onRetry;
  @override
  Widget build(BuildContext context) => Center(
      child: Padding(padding: const EdgeInsets.all(24),
        child: Column(mainAxisSize: MainAxisSize.min, children: [
          const Icon(Icons.wifi_off, size: 48, color: Colors.grey),
          const SizedBox(height: 12),
          const Text('Cannot reach agent',
              style: TextStyle(fontWeight: FontWeight.bold)),
          const SizedBox(height: 8),
          Text(message, textAlign: TextAlign.center,
              style: const TextStyle(color: Colors.grey, fontSize: 12)),
          const SizedBox(height: 16),
          FilledButton.icon(
            onPressed: onRetry,
            icon: const Icon(Icons.refresh),
            label: const Text('Retry'),
          ),
        ])));
}
