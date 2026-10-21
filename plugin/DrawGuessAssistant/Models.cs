using System.Collections.Generic;

namespace DrawGuessAssistant
{
    /// <summary>Shape of <c>strokes.json</c> written by the Python helper.</summary>
    public class StrokesData
    {
        public string word;
        public string query;
        public float aspect;
        public List<StrokeData> strokes;
    }

    public class StrokeData
    {
        /// <summary>Normalised points [[x,y],...] with x in [0,1] left->right and y in [0,1] bottom->top.</summary>
        public List<List<float>> points;
        public int width;
        public List<int> color;
        /// <summary>True = a single fill point (call the game's fill tool); false = a line stroke.</summary>
        public bool fill;
    }

    /// <summary>Shape of <c>candidates.json</c> written by the Python helper.</summary>
    public class CandidatesData
    {
        public string word;
        public int count;
        public List<string> queries;
    }

    /// <summary>Shape of <c>settings.json</c>, shared between plugin and helper.</summary>
    public class SettingsData
    {
        public string search_mode = "auto";   // "auto" | "manual"
        public bool fill_enabled = true;
    }
}
