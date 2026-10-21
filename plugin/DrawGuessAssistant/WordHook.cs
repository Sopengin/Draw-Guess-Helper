using System;
using System.IO;
using System.Reflection;
using HarmonyLib;

namespace DrawGuessAssistant
{
    /// <summary>
    /// Captures the word handed to the drawer. In auto-search mode the word is
    /// dropped into the shared runtime directory for the Python helper; in
    /// manual-search mode the player types their own query instead.
    /// </summary>
    public static class WordHook
    {
        public static void Patch(Harmony harmony)
        {
            MethodInfo setWord = typeof(IngameDrawModule).GetMethod(
                "SetWord",
                BindingFlags.Instance | BindingFlags.NonPublic | BindingFlags.Public,
                null,
                new[] { typeof(string), typeof(bool) },
                null);

            if (setWord == null)
                return;

            harmony.Patch(
                setWord,
                postfix: new HarmonyMethod(typeof(WordHook).GetMethod(nameof(OnSetWord), BindingFlags.Static | BindingFlags.NonPublic)));
        }

        private static void OnSetWord(object[] __args)
        {
            if (AppState.SearchMode != "auto")
                return;
            if (__args == null || __args.Length == 0)
                return;
            if (!(__args[0] is string word) || string.IsNullOrEmpty(word))
                return;

            try
            {
                File.WriteAllText(AppState.WordFile, word);
            }
            catch (Exception)
            {
                // Never let the hook break the game.
            }
        }
    }
}
