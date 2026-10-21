using System;
using System.IO;
using BepInEx;
using BepInEx.Unity.Mono;
using HarmonyLib;
using UnityEngine;

namespace DrawGuessAssistant
{
    [BepInPlugin(Guid, Name, Version)]
    public class Plugin : BaseUnityPlugin
    {
        public const string Guid = "com.drawguess.assistant";
        public const string Name = "Draw & Guess Assistant";
        public const string Version = "1.0.0";

        // Shared directory used for the word.txt / strokes.json handshake with
        // the Python helper. Override with the DRAWGUESS_RUNTIME_DIR env var.
        private static readonly string DefaultRuntimeDir =
            @"D:\CodeRepo\REA\draw&guess\runtime";

        private void Awake()
        {
            string runtimeDir = Environment.GetEnvironmentVariable("DRAWGUESS_RUNTIME_DIR");
            if (string.IsNullOrEmpty(runtimeDir))
                runtimeDir = DefaultRuntimeDir;

            try
            {
                Directory.CreateDirectory(runtimeDir);
            }
            catch (Exception)
            {
                // Fall through; hooks will just fail to write.
            }

            AppState.RuntimeDir = runtimeDir;
            AppState.LoadSettings();

            var harmony = new Harmony(Guid);
            WordHook.Patch(harmony);

            var go = new GameObject("DrawGuessAssistantBehaviour");
            DontDestroyOnLoad(go);
            go.AddComponent<AssistantBehaviour>().Configure(runtimeDir, animateSpeedMs: 0);

            Logger.LogInfo($"{Name} v{Version} loaded. runtime={runtimeDir}");
        }
    }
}
