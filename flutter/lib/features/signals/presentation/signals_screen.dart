import 'package:flutter/material.dart';
import 'package:flutter_bloc/flutter_bloc.dart';
import '../../../core/models/agent_models.dart';
import '../bloc/signals_bloc.dart';

class SignalsScreen extends StatelessWidget {
  const SignalsScreen({super.key});
  @override
  // BLoC is provided by MultiBlocProvider in HomeScreen.
  Widget build(BuildContext context) => const _SignalsView();
}

class _SignalsView extends StatelessWidget {
  const _SignalsView();
  @override
  Widget build(BuildContext context) {
    return DefaultTabController(
      length: 2,
      child: Scaffold(
        appBar: AppBar(
          title: const Text('Signals & Positions'),
          bottom: const TabBar(tabs: [
            Tab(icon: Icon(Icons.bolt), text: 'Signals'),
            Tab(icon: Icon(Icons.receipt_long), text: 'Positions'),
          ]),
          actions: [IconButton(
            icon: const Icon(Icons.refresh),
            onPressed: () => context
                .read<SignalsBloc>().add(SignalsRefreshRequested()),
          )],
        ),
        body: BlocBuilder<SignalsBloc, SignalsState>(
          builder: (context, state) {
            if (state.status == SignalsStatus.loading)
              return const Center(child: CircularProgressIndicator());
            if (state.status == SignalsStatus.failure)
              return Center(child: Padding(
                padding: const EdgeInsets.all(24),
                child: Column(mainAxisSize: MainAxisSize.min, children: [
                  const Icon(Icons.wifi_off, size: 48, color: Colors.grey),
                  const SizedBox(height: 12),
                  Text(state.errorMessage, textAlign: TextAlign.center,
                      style: const TextStyle(color: Colors.grey, fontSize: 13)),
                  const SizedBox(height: 16),
                  FilledButton.icon(
                    onPressed: () => context.read<SignalsBloc>().add(SignalsRefreshRequested()),
                    icon: const Icon(Icons.refresh),
                    label: const Text('Retry'),
                  ),
                ]),
              ));
            return TabBarView(children: [
              _SignalsList(signals: state.signals),
              _PositionsList(positions: state.positions),
            ]);
          },
        ),
      ),
    );
  }
}

class _SignalsList extends StatelessWidget {
  const _SignalsList({required this.signals});
  final List<SignalItem> signals;
  @override
  Widget build(BuildContext context) {
    if (signals.isEmpty) return const Center(
        child: Column(mainAxisSize: MainAxisSize.min, children: [
          Icon(Icons.radar, size: 48, color: Colors.grey),
          SizedBox(height: 12),
          Text('No signals yet', style: TextStyle(color: Colors.grey)),
          Text('Swarm fires after 25 queued markets',
              style: TextStyle(color: Colors.grey, fontSize: 12)),
        ]));
    return ListView.separated(
      padding: const EdgeInsets.all(8),
      itemCount: signals.length,
      separatorBuilder: (_, __) => const Divider(height: 1),
      itemBuilder: (_, i) => _SignalTile(signal: signals[i]),
    );
  }
}

class _SignalTile extends StatelessWidget {
  const _SignalTile({required this.signal});
  final SignalItem signal;
  @override
  Widget build(BuildContext context) {
    final isArb = signal.sourceEnum == SignalSource.arb;
    final isYes = signal.consensus == 'YES';
    final isNo  = signal.consensus == 'NO';
    final dc = isYes ? Colors.green
        : isNo ? Colors.red
        : isArb ? Colors.deepPurple : Colors.orange;
    return ListTile(
      contentPadding:
          const EdgeInsets.symmetric(horizontal: 16, vertical: 6),
      leading: CircleAvatar(
        backgroundColor: dc.withOpacity(0.15),
        child: Text(isArb ? '⚡' : isYes ? '✅' : isNo ? '❌' : '⏸',
            style: const TextStyle(fontSize: 18)),
      ),
      title: Text(signal.question, maxLines: 2,
          overflow: TextOverflow.ellipsis,
          style: const TextStyle(fontSize: 13)),
      subtitle: Padding(
        padding: const EdgeInsets.only(top: 4),
        child: Row(children: [
          _Badge(isArb ? 'ARB' : signal.source, Colors.grey.shade300),
          const SizedBox(width: 6),
          _Badge(signal.consensus, dc.withOpacity(0.2)),
          const Spacer(),
          if (!isArb)
            Text('${signal.yesCount}Y/${signal.noCount}N',
                style: TextStyle(fontSize: 11, color: Colors.grey.shade600)),
        ]),
      ),
      trailing: Column(mainAxisAlignment: MainAxisAlignment.center, children: [
        Text(
          isArb
              ? '\$${(signal.confidence * 100).toStringAsFixed(1)}c'
              : '${(signal.confidence * 100).toStringAsFixed(0)}%',
          style: TextStyle(fontWeight: FontWeight.bold, color: dc, fontSize: 14),
        ),
        Text(isArb ? 'edge' : 'conf.',
            style: TextStyle(fontSize: 9, color: Colors.grey.shade500)),
      ]),
    );
  }
}

class _PositionsList extends StatelessWidget {
  const _PositionsList({required this.positions});
  final List<OrderItem> positions;
  @override
  Widget build(BuildContext context) {
    if (positions.isEmpty) return const Center(
        child: Column(mainAxisSize: MainAxisSize.min, children: [
          Icon(Icons.inbox_outlined, size: 48, color: Colors.grey),
          SizedBox(height: 12),
          Text('No paper trades yet', style: TextStyle(color: Colors.grey)),
        ]));
    final totalPaper = positions
        .where((o) => o.statusEnum == OrderStatusEnum.paper)
        .fold(0.0, (sum, o) => sum + o.sizeUsd);
    return Column(children: [
      Padding(padding: const EdgeInsets.all(12),
        child: Row(children: [
          _Badge('${positions.length} orders', Colors.blue.shade100),
          const SizedBox(width: 8),
          _Badge('Paper: \$${totalPaper.toStringAsFixed(2)}', Colors.green.shade100),
        ])),
      Expanded(child: ListView.separated(
        padding: const EdgeInsets.symmetric(horizontal: 8),
        itemCount: positions.length,
        separatorBuilder: (_, __) => const Divider(height: 1),
        itemBuilder: (_, i) => _PositionTile(order: positions[i]),
      )),
    ]);
  }
}

class _PositionTile extends StatelessWidget {
  const _PositionTile({required this.order});
  final OrderItem order;
  @override
  Widget build(BuildContext context) {
    final sc = switch (order.statusEnum) {
      OrderStatusEnum.paper      => Colors.blue,
      OrderStatusEnum.filled     => Colors.green,
      OrderStatusEnum.killed     => Colors.red,
      OrderStatusEnum.rateLimited => Colors.orange,
      _                          => Colors.grey,
    };
    final sideIsYes = order.sideEnum == TradeOutcome.yes;
    return ListTile(
      contentPadding: const EdgeInsets.symmetric(horizontal: 16, vertical: 4),
      leading: Container(
        padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 4),
        decoration: BoxDecoration(
          color: sideIsYes ? Colors.green.shade100 : Colors.red.shade100,
          borderRadius: BorderRadius.circular(6),
        ),
        child: Text(order.sideEnum.label, style: TextStyle(
            color: sideIsYes
                ? Colors.green.shade800 : Colors.red.shade800,
            fontWeight: FontWeight.bold, fontSize: 11)),
      ),
      title: Text(order.question, maxLines: 2,
          overflow: TextOverflow.ellipsis,
          style: const TextStyle(fontSize: 13)),
      subtitle: Row(children: [
        _Badge(order.source, Colors.grey.shade200),
        const SizedBox(width: 6),
        _Badge(order.status, sc.withOpacity(0.2)),
        const Spacer(),
        Text('@${order.price.toStringAsFixed(3)}',
            style: TextStyle(fontSize: 11, color: Colors.grey.shade600)),
      ]),
      trailing: Text('\$${order.sizeUsd.toStringAsFixed(2)}',
          style: const TextStyle(fontWeight: FontWeight.bold, fontSize: 14)),
    );
  }
}

class _Badge extends StatelessWidget {
  const _Badge(this.label, this.color);
  final String label;
  final Color color;
  @override
  Widget build(BuildContext context) => Container(
      padding: const EdgeInsets.symmetric(horizontal: 6, vertical: 2),
      decoration: BoxDecoration(
          color: color, borderRadius: BorderRadius.circular(4)),
      child: Text(label, style: const TextStyle(fontSize: 10)));
}
