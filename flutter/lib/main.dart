import 'package:flutter/material.dart';
import 'core/di/injection.dart';
import 'app.dart';

void main() async {
  WidgetsFlutterBinding.ensureInitialized();
  // Awaited — the UI never builds before services are fully registered.
  // Safe to add async setup (DB, remote config, etc.) in configureDependencies().
  await configureDependencies();
  runApp(const PolyShadowApp());
}
