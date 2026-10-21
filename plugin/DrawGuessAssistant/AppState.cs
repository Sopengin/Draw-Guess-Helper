using System.IO;
using Newtonsoft.Json;

namespace DrawGuessAssistant
{
    /// <summary>Shared plugin state and the runtime settings.json persistence.</summary>
    public static class AppState
    {
        public static string RuntimeDir;
        public static string SearchMode = "auto";   // "auto" | "manual"
        public static bool FillEnabled = true;

        public static string WordFile => Path.Combine(RuntimeDir, "word.txt");
        public static string SettingsFile => Path.Combine(RuntimeDir, "settings.json");

        public static void LoadSettings()
        {
            try
            {
                if (File.Exists(SettingsFile))
                {
                    SettingsData d = JsonConvert.DeserializeObject<SettingsData>(File.ReadAllText(SettingsFile));
                    if (d != null)
                    {
                        SearchMode = d.search_mode == "manual" ? "manual" : "auto";
                        FillEnabled = d.fill_enabled;
                    }
                }
            }
            catch (System.Exception)
            {
                // keep defaults
            }
        }

        public static void SaveSettings()
        {
            try
            {
                SettingsData d = new SettingsData { search_mode = SearchMode, fill_enabled = FillEnabled };
                File.WriteAllText(SettingsFile, JsonConvert.SerializeObject(d));
            }
            catch (System.Exception)
            {
                // ignore write failures
            }
        }
    }
}
