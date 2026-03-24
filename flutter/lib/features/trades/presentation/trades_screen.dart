import 'package:flutter/material.dart';
import 'package:flutter_bloc/flutter_bloc.dart';
import '../../../core/models/agent_models.dart';
import '../bloc/trades_bloc.dart';

class TradesScreen extends StatelessWidget {
  const TradesScreen({super.key});
  @override
  // BLoC is provided by MultiBlocProvider in HomeScreen.
  Widget build(BuildContext context) => const _TradesView();
}

class _TradesView extends StatelessWidget {
  const _TradesView();
  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: const Text('🐋 Whale Feed'),
        actions: [IconButton(
          icon: const Icon(Icons.refresh),
          onPressed: () =>
              context.read<TradesBloc>().add(TradesRefreshRequested()),
        )],
      ),
      body: BlocBuilder<TradesBloc, TradesState>(
        builder: (context, state) {
          if (state.status == TradesStatus.loading)
            return const Center(child: CircularProgressIndicator());
          if (state.status == TradesStatus.failure)
            return Center(child: Padding(
              padding: const EdgeInsets.all(24),
              child: Column(mainAxisSize: MainAxisSize.min, children: [
                const Icon(Icons.wifi_off, size: 48, color: Colors.grey),
                const SizedBox(height: 12),
                Text(state.errorMessage, textAlign: TextAlign.center,
                    style: const TextStyle(color: Colors.grey, fontSize: 13)),
                const SizedBox(height: 16),
                FilledButton.icon(
                  onPressed: () => context.read<TradesBloc>().add(TradesRefreshRequested()),
                  icon: const Icon(Icons.refresh),
                  label: const Text('Retry'),
                ),
              ]),
            ));
          if (state.trades.isEmpty)
            return const Center(child: Column(
                mainAxisSize: MainAxisSize.min, children: [
              Icon(Icons.hourglass_empty, size: 48, color: Colors.grey),
              SizedBox(height: 12),
              Text('Waiting for whale trades...',
                  style: TextStyle(color: Colors.grey)),
              Text('Threshold: \$500+',
                  style: TextStyle(color: Colors.grey, fontSize: 12)),
            ]));
          return RefreshIndicator(
            onRefresh: () async =>
                context.read<TradesBloc>().add(TradesRefreshRequested()),
            child: ListView.separated(
              padding: const EdgeInsets.all(8),
              itemCount: state.trades.length,
              separatorBuilder: (_, __) => const Divider(height: 1),
              itemBuilder: (_, i) => _TradeTile(trade: state.trades[i]),
            ),
          );
        },
      ),
    );
  }
}

class _TradeTile extends StatelessWidget {
  const _TradeTile({required this.trade});
  final TradeItem trade;
  @override
  Widget build(BuildContext context) {
    final isYes   = trade.outcomeEnum == TradeOutcome.yes;
    final isLarge = trade.amountUsd >= 2000;
    return ListTile(
      contentPadding:
          const EdgeInsets.symmetric(horizontal: 16, vertical: 4),
      leading: Container(
        padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 4),
        decoration: BoxDecoration(
          color: isYes ? Colors.green.shade100 : Colors.red.shade100,
          borderRadius: BorderRadius.circular(6),
        ),
        child: Text(trade.outcomeEnum.label,
            style: TextStyle(
                color: isYes ? Colors.green.shade800 : Colors.red.shade800,
                fontWeight: FontWeight.bold, fontSize: 12)),
      ),
      title: Text(trade.question, maxLines: 2,
          overflow: TextOverflow.ellipsis,
          style: const TextStyle(fontSize: 13)),
      subtitle: Row(children: [
        if (trade.category.isNotEmpty)
          Chip(label: Text(trade.category,
              style: const TextStyle(fontSize: 10)),
            padding: EdgeInsets.zero,
            visualDensity: VisualDensity.compact),
        const Spacer(),
        Text('@${trade.price.toStringAsFixed(3)}',
            style: TextStyle(color: Colors.grey.shade600, fontSize: 11)),
      ]),
      trailing: Column(mainAxisAlignment: MainAxisAlignment.center, children: [
        Text(
          '\$${trade.amountUsd >= 1000 ? '${(trade.amountUsd/1000).toStringAsFixed(1)}k' : trade.amountUsd.toStringAsFixed(0)}',
          style: TextStyle(fontWeight: FontWeight.bold, fontSize: 15,
              color: isLarge ? Colors.deepPurple : null),
        ),
        if (isLarge) const Text('BIG 🐋',
            style: TextStyle(fontSize: 9, color: Colors.deepPurple)),
      ]),
    );
  }
}
