import 'package:get_it/get_it.dart';
import '../api/agent_api.dart';

final getIt = GetIt.instance;

/// Returns a Future so callers can await full initialisation before
/// the UI starts building. Add any async setup (e.g. local DB, remote
/// config) inside this function and the app will wait for it safely.
Future<void> configureDependencies() async {
  getIt.registerLazySingleton<AgentApi>(() => AgentApi());
}
