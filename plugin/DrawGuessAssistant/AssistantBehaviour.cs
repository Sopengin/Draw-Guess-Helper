using System.Collections.Generic;
using System.IO;
using Newtonsoft.Json;
using UnityEngine;

namespace DrawGuessAssistant
{
    /// <summary>
    /// Runs on Unity's main thread. Handles three things:
    /// * a settings panel (F8) to toggle auto/manual search and fill on/off;
    /// * the in-game candidate preview (click to pick, or skip);
    /// * replaying strokes.json into the canvas.
    /// </summary>
    public class AssistantBehaviour : MonoBehaviour
    {
        private string strokesFile;
        private string candidatesFile;
        private string choiceFile;
        private string previewDir;
        private int animateMs;

        private bool animating;
        private List<StrokeData> pending;
        private int nextStroke;
        private float nextTickTime;
        private float drawingAspect = 1f;

        private bool showingPreview;
        private string previewWord = "";
        private readonly List<Texture2D> previewTextures = new List<Texture2D>();

        private bool showSettings = true;
        private string manualQuery = "";

        private GUIStyle titleStyle;
        private GUIStyle labelStyle;
        private bool stylesReady;

        public void Configure(string runtimeDir, int animateSpeedMs)
        {
            strokesFile = Path.Combine(runtimeDir, "strokes.json");
            candidatesFile = Path.Combine(runtimeDir, "candidates.json");
            choiceFile = Path.Combine(runtimeDir, "choice.txt");
            previewDir = Path.Combine(runtimeDir, "preview");
            animateMs = animateSpeedMs;
        }

        private void Update()
        {
            if (!showingPreview && !animating && File.Exists(candidatesFile))
                TryShowPreview();

            if (!showingPreview && !animating && File.Exists(strokesFile))
                TryConsumeStrokes();

            if (animating)
                AdvanceAnimation();
        }

        private void OnGUI()
        {
            EnsureStyles();

            Event e = Event.current;
            if (e != null && e.type == EventType.KeyDown && e.keyCode == KeyCode.F8)
            {
                showSettings = !showSettings;
                e.Use();
            }

            if (showingPreview)
            {
                RenderPreview();
                return;
            }

            if (showSettings)
                RenderSettings();
            else
                GUI.Label(new Rect(Screen.width - 150, Screen.height - 30, 150, 26), "F8 设置", labelStyle);
        }

        // ------------------------------------------------------------------
        // Settings UI
        // ------------------------------------------------------------------

        private void RenderSettings()
        {
            GUILayout.BeginArea(new Rect(20, 20, 360, 360));
            GUILayout.BeginVertical("box");
            GUILayout.Label("Draw & Guess 助手设置", titleStyle);
            GUILayout.Space(8);

            if (GUILayout.Button("搜索模式：" + (AppState.SearchMode == "auto" ? "自动" : "手动"), GUILayout.Height(34)))
            {
                AppState.SearchMode = AppState.SearchMode == "auto" ? "manual" : "auto";
                AppState.SaveSettings();
            }

            if (GUILayout.Button("填色：" + (AppState.FillEnabled ? "开" : "关"), GUILayout.Height(34)))
            {
                AppState.FillEnabled = !AppState.FillEnabled;
                AppState.SaveSettings();
            }

            if (AppState.SearchMode == "manual")
            {
                GUILayout.Label("手动搜索词（输入后点搜索）：", labelStyle);
                manualQuery = GUILayout.TextField(manualQuery, GUILayout.Height(30));
                if (GUILayout.Button("搜索", GUILayout.Height(34)) && !string.IsNullOrEmpty(manualQuery.Trim()))
                {
                    try { File.WriteAllText(AppState.WordFile, manualQuery.Trim()); } catch (System.Exception) { }
                }
            }

            GUILayout.Space(10);
            GUILayout.Label("自动 = 按题面搜图；手动 = 自己输入搜索词。", labelStyle);
            if (GUILayout.Button("关闭设置", GUILayout.Height(30)))
                showSettings = false;

            GUILayout.EndVertical();
            GUILayout.EndArea();
        }

        // ------------------------------------------------------------------
        // Preview UI
        // ------------------------------------------------------------------

        private void TryShowPreview()
        {
            try
            {
                string json = File.ReadAllText(candidatesFile);
                CandidatesData data = JsonConvert.DeserializeObject<CandidatesData>(json);
                if (data == null || data.count <= 0)
                    return;

                previewTextures.Clear();
                for (int i = 0; i < data.count; i++)
                {
                    string path = Path.Combine(previewDir, i + ".png");
                    if (!File.Exists(path))
                        continue;
                    Texture2D tex = new Texture2D(2, 2);
                    if (ImageConversion.LoadImage(tex, File.ReadAllBytes(path)))
                        previewTextures.Add(tex);
                    else
                        Destroy(tex);
                }

                previewWord = data.word ?? "";
                showingPreview = previewTextures.Count > 0;
                if (!showingPreview)
                    TryDelete(candidatesFile);
            }
            catch (System.Exception)
            {
                // Partial/corrupt file; leave for next poll.
            }
        }

        private void RenderPreview()
        {
            Color prev = GUI.color;
            GUI.color = new Color(0f, 0f, 0f, 0.85f);
            GUI.DrawTexture(new Rect(0, 0, Screen.width, Screen.height), Texture2D.whiteTexture);
            GUI.color = prev;

            GUI.Label(new Rect(30, 24, Screen.width - 60, 46),
                "题目：" + previewWord + "  —— 点选一张自动作画，或跳过自己画", titleStyle);

            float box = Mathf.Clamp(Screen.width / (previewTextures.Count + 1) - 24f, 120f, 260f);
            float y = 110f;
            float x = 30f;
            float gap = 24f;

            for (int i = 0; i < previewTextures.Count; i++)
            {
                Texture2D tex = previewTextures[i];
                float aspect = (float)tex.width / Mathf.Max(1, tex.height);
                float w = box, h = box;
                if (aspect > 1f) h = box / aspect; else w = box * aspect;

                Rect imgRect = new Rect(x + (box - w) * 0.5f, y, w, h);
                if (GUI.Button(imgRect, new GUIContent(tex)))
                {
                    Choose(i);
                    return;
                }
                GUI.Label(new Rect(x, y + box + 6, box, 24), "图 " + (i + 1), labelStyle);
                x += box + gap;
            }

            if (GUI.Button(new Rect(30, y + box + 52, 220, 44), "跳过 · 我自己画"))
            {
                ChooseSkip();
            }
        }

        private void Choose(int i)
        {
            try { File.WriteAllText(choiceFile, i.ToString()); } catch (System.Exception) { }
            TryDelete(candidatesFile);
            HidePreview();
        }

        private void ChooseSkip()
        {
            try { File.WriteAllText(choiceFile, "skip"); } catch (System.Exception) { }
            TryDelete(candidatesFile);
            HidePreview();
        }

        private void HidePreview()
        {
            showingPreview = false;
            foreach (Texture2D t in previewTextures)
                if (t != null)
                    Destroy(t);
            previewTextures.Clear();
            previewWord = "";
        }

        // ------------------------------------------------------------------
        // Drawing
        // ------------------------------------------------------------------

        private void TryConsumeStrokes()
        {
            try
            {
                string json = File.ReadAllText(strokesFile);
                StrokesData data = JsonConvert.DeserializeObject<StrokesData>(json);

                TryDelete(strokesFile);

                if (data != null && data.strokes != null && data.strokes.Count > 0)
                {
                    drawingAspect = data.aspect > 0f ? data.aspect : 1f;
                    pending = data.strokes;
                    nextStroke = 0;
                    nextTickTime = Time.time;
                    animating = true;
                }
            }
            catch (System.Exception)
            {
                // Corrupt/partial file; leave it for the next poll.
            }
        }

        private void AdvanceAnimation()
        {
            if (!DrawInjector.TryComputeMapping(drawingAspect, out Vector2 origin, out Vector2 scale))
                return;

            if (animateMs <= 0)
            {
                for (int i = nextStroke; i < pending.Count; i++)
                    DrawInjector.DrawStroke(pending[i], origin, scale);
                animating = false;
                pending = null;
                return;
            }

            if (Time.time >= nextTickTime && nextStroke < pending.Count)
            {
                DrawInjector.DrawStroke(pending[nextStroke], origin, scale);
                nextStroke++;
                nextTickTime = Time.time + animateMs / 1000f;
            }

            if (nextStroke >= pending.Count)
            {
                animating = false;
                pending = null;
            }
        }

        // ------------------------------------------------------------------
        // Misc
        // ------------------------------------------------------------------

        private void EnsureStyles()
        {
            if (stylesReady)
                return;
            titleStyle = new GUIStyle(GUI.skin.label)
            {
                fontSize = 20,
                fontStyle = FontStyle.Bold,
                alignment = TextAnchor.MiddleLeft
            };
            labelStyle = new GUIStyle(GUI.skin.label)
            {
                fontSize = 16,
                alignment = TextAnchor.MiddleLeft
            };
            stylesReady = true;
        }

        private static void TryDelete(string path)
        {
            try { if (File.Exists(path)) File.Delete(path); } catch (System.Exception) { }
        }
    }
}
