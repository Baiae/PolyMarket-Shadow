import 'package:flutter/material.dart';
import 'package:flutter_bloc/flutter_bloc.dart';
import '../../../core/di/injection.dart';
import '../../../core/api/agent_api.dart';
import '../../dashboard/bloc/dashboard_bloc.dart';
import '../../dashboard/presentation/dashboard_screen.dart';
import '../../trades/bloc/trades_bloc.dart';
import '../../trades/presentation/trades_screen.dart';
import '../../signals/bloc/signals_bloc.dart';
import '../../signals/presentation/signals_screen.dart';

/// All three BLoCs are provided here at HomeScreen level so they survive
/// tab switches and are never recreated when the user changes tabs.
class HomeScreen extends StatefulWidget {
  const HomeScreen({super.key});
  @override
  State<HomeScreen> createState() => _HomeScreenState();
}

class _HomeScreenState extends State<HomeScreen> {
  int _currentIndex = 0;

  static const _screens = [
    DashboardScreen(),
    TradesScreen(),
    SignalsScreen(),
  ];

  @override
  Widget build(BuildContext context) {
    return MultiBlocProvider(
      providers: [
        BlocProvider<DashboardBloc>(
            create: (_) => DashboardBloc(getIt<AgentApi>())),
        BlocProvider<TradesBloc>(
            create: (_) => TradesBloc(getIt<AgentApi>())),
        BlocProvider<SignalsBloc>(
            create: (_) => SignalsBloc(getIt<AgentApi>())),
      ],
      child: Scaffold(
        body: IndexedStack(index: _currentIndex, children: _screens),
        bottomNavigationBar: NavigationBar(
          selectedIndex: _currentIndex,
          onDestinationSelected: (i) => setState(() => _currentIndex = i),
          destinations: const [
            NavigationDestination(
              icon: Icon(Icons.monitor_heart_outlined),
              selectedIcon: Icon(Icons.monitor_heart),
              label: 'Status',
            ),
            NavigationDestination(
              icon: Icon(Icons.waves_outlined),
              selectedIcon: Icon(Icons.waves),
              label: 'Whales',
            ),
            NavigationDestination(
              icon: Icon(Icons.bolt_outlined),
              selectedIcon: Icon(Icons.bolt),
              label: 'Signals',
            ),
          ],
        ),
      ),
    );
  }
}
