using System.Collections.Generic;
using System.Reflection;
using UnityEngine;

namespace DrawGuessAssistant
{
    /// <summary>
    /// Replays a stroke through the game's own drawing path.
    ///
    /// The relevant DrawModule methods are private/protected, so we invoke
    /// them reflectively. This is the exact code path the mouse uses:
    ///   CreateNewLine() -> TryAddNewPointToCurrentLine(world, isNotFirst)
    ///                   -> FinishLine(false)
    /// which means rendering, colliders, undo and network sync all work.
    /// </summary>
    public static class DrawInjector
    {
        private static readonly MethodInfo CreateNewLine =
            typeof(DrawModule).GetMethod("CreateNewLine", BindingFlags.Instance | BindingFlags.NonPublic);

        private static readonly MethodInfo TryAddPoint =
            typeof(DrawModule).GetMethod(
                "TryAddNewPointToCurrentLine",
                BindingFlags.Instance | BindingFlags.NonPublic,
                null,
                new[] { typeof(Vector2), typeof(bool) },
                null);

        private static readonly MethodInfo FinishLine =
            typeof(DrawModule).GetMethod(
                "FinishLine",
                BindingFlags.Instance | BindingFlags.NonPublic,
                null,
                new[] { typeof(bool) },
                null);

        // Fill tool: CreateNewFill(point) traces the enclosing lines and fills the
        // region with the current colour. It is private, so invoke reflectively.
        private static readonly MethodInfo CreateNewFill =
            typeof(DrawModule).GetMethod(
                "CreateNewFill",
                BindingFlags.Instance | BindingFlags.NonPublic,
                null,
                new[] { typeof(Vector2) },
                null);

        /// <summary>
        /// Compute the world-space rectangle the normalised drawing is fitted
        /// into, preserving the image's aspect ratio (centred, letterboxed).
        /// </summary>
        public static bool TryComputeMapping(float aspect, out Vector2 origin, out Vector2 scale)
        {
            origin = Vector2.zero;
            scale = Vector2.zero;

            DrawModule dm = DrawModule.DrawModuleInstance;
            DrawableSurface surface = dm != null ? dm.DrawSurface : null;
            if (surface == null)
                return false;

            float minX = surface.MinX, maxX = surface.MaxX;
            float minY = surface.MinY, maxY = surface.MaxY;
            float canvasW = maxX - minX, canvasH = maxY - minY;
            if (canvasW <= 0f || canvasH <= 0f || aspect <= 0f)
                return false;

            float drawW, drawH;
            if (canvasW / canvasH > aspect)
            {
                drawH = canvasH;
                drawW = canvasH * aspect;
            }
            else
            {
                drawW = canvasW;
                drawH = canvasW / aspect;
            }

            origin = new Vector2(minX + (canvasW - drawW) * 0.5f, minY + (canvasH - drawH) * 0.5f);
            scale = new Vector2(drawW, drawH);
            return true;
        }

        /// <summary>Draw a single stroke immediately, applying its colour first.</summary>
        public static void DrawStroke(StrokeData stroke, Vector2 origin, Vector2 scale)
        {
            DrawModule dm = DrawModule.DrawModuleInstance;
            if (dm == null || stroke == null || stroke.points == null || stroke.points.Count == 0)
                return;

            ApplyColor(dm, stroke);

            if (stroke.fill)
            {
                // Fill stroke: a single interior point -> call the game's fill tool.
                Vector2 world = MapPoint(stroke.points[0], origin, scale);
                if (CreateNewFill == null)
                {
                    Debug.LogError("[DrawGuessAssistant] CreateNewFill reflection lookup failed");
                    return;
                }
                try
                {
                    CreateNewFill.Invoke(dm, new object[] { world });
                }
                catch (System.Exception e)
                {
                    Debug.LogError("[DrawGuessAssistant] fill failed: " + e);
                }
                return;
            }

            CreateNewLine.Invoke(dm, null);
            for (int i = 0; i < stroke.points.Count; i++)
            {
                var p = stroke.points[i];
                if (p == null || p.Count < 2)
                    continue;
                Vector2 world = MapPoint(p, origin, scale);
                TryAddPoint.Invoke(dm, new object[] { world, i > 0 });
            }
            FinishLine.Invoke(dm, new object[] { false });
        }

        private static void ApplyColor(DrawModule dm, StrokeData stroke)
        {
            if (stroke.color != null && stroke.color.Count >= 3)
            {
                var c = new Color(
                    stroke.color[0] / 255f,
                    stroke.color[1] / 255f,
                    stroke.color[2] / 255f,
                    1f);
                dm.SetRGBColor(c, true, true, false, false, false);
            }
        }

        private static Vector2 MapPoint(List<float> p, Vector2 origin, Vector2 scale)
        {
            return new Vector2(origin.x + p[0] * scale.x, origin.y + p[1] * scale.y);
        }
    }
}
