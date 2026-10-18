using System;
using System.Collections.Concurrent;
using System.Diagnostics;
using System.IO;
using System.Linq;
using System.Text;
using UnityEditor;
using UnityEditor.SceneManagement;
using UnityEngine;
using Debug = UnityEngine.Debug;

/// <summary>
/// Window "Hanoi/City Generator": pick (or drop) an .osm file and get a scene of that area.
///   1. python Map/osm_pipeline.py &lt;file.osm&gt; --out Map/out_&lt;slug&gt;   (child process, log shown here)
///   2. CityPlacer.Run  -> Assets/Hanoi/Areas/&lt;slug&gt;/Chunks + &lt;slug&gt;_Main.unity   (houses, ground, trees, bikes, props)
///   3. ChunkBuilder.Run (HLOD for the far view)
///   4. FlyoverBuilder.Build (flyovers found in the OSM data, own scene Flyovers.unity)
///   5. open the result
/// Every area is a CityTarget of its own (CityTarget.Area), the main map and its Build Settings stay untouched.
/// The Blender-made assets (library, trees, bikes, props) must already be imported in the project.
/// </summary>
public class CityGenerator : EditorWindow
{
    const string PrefPython = "Hanoi.CityGenerator.python";
    const string PrefLastDir = "Hanoi.CityGenerator.lastDir";

    // inputs
    string osmPath = "", areaName = "";
    bool nameTouched;
    bool trees = true, motos = true, props = true, flyovers = true, hlod = true, openAfter = true;
    string python;

    // state
    enum Stage { Idle, Pipeline, Unity }
    Stage stage = Stage.Idle;
    Process proc;
    readonly ConcurrentQueue<string> lines = new ConcurrentQueue<string>();
    readonly StringBuilder log = new StringBuilder();
    string lastLine = "", pythonStatus = "";
    bool pythonOk;
    Vector2 logScroll;
    CityTarget.T target;
    int errorsSeen;
    DateTime started;

    [MenuItem("Hanoi/City Generator")]
    public static void Open()
    {
        var w = GetWindow<CityGenerator>("City Generator");
        w.minSize = new Vector2(460f, 520f);
    }

    void OnEnable()
    {
        python = EditorPrefs.GetString(PrefPython, "python");
        CheckPython();
        EditorApplication.update += Tick;
    }

    void OnDisable()
    {
        EditorApplication.update -= Tick;
        Kill();
    }

    // ------------------------------------------------------------------ helpers
    static string MapDir => Path.GetFullPath(Path.Combine(HanoiSetup.ProjectDir, "../Map"));

    /// "Chùa Bộc (1).osm" -> "chua_boc_1": a name safe for folders, scene names and the chunk prefix.
    public static string Slug(string s)
    {
        var d = (s ?? "").Replace('đ', 'd').Replace('Đ', 'D').Normalize(NormalizationForm.FormD);
        var sb = new StringBuilder();
        foreach (char c in d)
        {
            if (System.Globalization.CharUnicodeInfo.GetUnicodeCategory(c) == System.Globalization.UnicodeCategory.NonSpacingMark) continue;
            char l = char.ToLowerInvariant(c);
            if ((l >= 'a' && l <= 'z') || (l >= '0' && l <= '9')) sb.Append(l);
            else if (sb.Length > 0 && sb[sb.Length - 1] != '_') sb.Append('_');
        }
        return sb.ToString().Trim('_');
    }

    string Slug() => Slug(areaName);

    void Log(string s)
    {
        log.AppendLine(s);
        lastLine = s;
        logScroll.y = float.MaxValue;
    }

    void SetOsm(string path)
    {
        osmPath = path;
        EditorPrefs.SetString(PrefLastDir, Path.GetDirectoryName(path) ?? "");
        if (!nameTouched || string.IsNullOrEmpty(areaName)) areaName = Slug(Path.GetFileNameWithoutExtension(path));
        Repaint();
    }

    void CheckPython()
    {
        pythonOk = false;
        try
        {
            var psi = new ProcessStartInfo(python, "-c \"import shapely,sys;print('Python', sys.version.split()[0], '/ shapely', shapely.__version__)\"")
            {
                UseShellExecute = false, CreateNoWindow = true, RedirectStandardOutput = true, RedirectStandardError = true,
            };
            using (var p = Process.Start(psi))
            {
                string o = p.StandardOutput.ReadToEnd().Trim(), e = p.StandardError.ReadToEnd().Trim();
                if (!p.WaitForExit(15000)) { try { p.Kill(); } catch { } pythonStatus = "Python không trả lời (quá 15 s)"; return; }
                if (p.ExitCode == 0) { pythonOk = true; pythonStatus = o; }
                else pythonStatus = e.Contains("shapely") ? "Python có nhưng thiếu shapely: pip install shapely" : "Python lỗi: " + e.Split('\n').LastOrDefault();
            }
        }
        catch (Exception ex) { pythonStatus = "Không chạy được '" + python + "': " + ex.Message; }
    }

    // ------------------------------------------------------------------ GUI
    void OnGUI()
    {
        bool busy = stage != Stage.Idle;
        EditorGUILayout.Space(4);
        EditorGUILayout.LabelField("Dựng khu vực từ file OpenStreetMap", EditorStyles.boldLabel);

        using (new EditorGUI.DisabledScope(busy))
        {
            DropZone();
            using (new EditorGUILayout.HorizontalScope())
            {
                osmPath = EditorGUILayout.TextField("File .osm", osmPath);
                if (GUILayout.Button("Chọn…", GUILayout.Width(60f)))
                {
                    string p = EditorUtility.OpenFilePanel("Chọn file OSM", EditorPrefs.GetString(PrefLastDir, ""), "osm");
                    if (!string.IsNullOrEmpty(p)) SetOsm(p);
                }
            }
            EditorGUI.BeginChangeCheck();
            areaName = EditorGUILayout.TextField("Tên khu vực", areaName);
            if (EditorGUI.EndChangeCheck()) nameTouched = true;
            string slug = Slug();
            EditorGUILayout.LabelField(" ", slug.Length == 0 ? "(chưa có tên)" : $"Assets/Hanoi/Areas/{slug}   ·   Map/out_{slug}", EditorStyles.miniLabel);

            EditorGUILayout.Space(2);
            EditorGUILayout.LabelField("Dựng gì", EditorStyles.boldLabel);
            using (new EditorGUILayout.HorizontalScope())
            {
                trees = GUILayout.Toggle(trees, "Cây");
                motos = GUILayout.Toggle(motos, "Xe máy đỗ");
                props = GUILayout.Toggle(props, "Cột điện / biển ngõ");
                flyovers = GUILayout.Toggle(flyovers, "Cầu vượt");
            }
            hlod = EditorGUILayout.ToggleLeft("HLOD (nhìn xa; tắt = nhanh hơn nhưng không thấy gì từ xa)", hlod);
            openAfter = EditorGUILayout.ToggleLeft("Mở scene khi xong", openAfter);

            EditorGUILayout.Space(2);
            using (new EditorGUILayout.HorizontalScope())
            {
                EditorGUI.BeginChangeCheck();
                python = EditorGUILayout.TextField("Python", python);
                if (EditorGUI.EndChangeCheck()) EditorPrefs.SetString(PrefPython, python);
                if (GUILayout.Button("Kiểm tra", GUILayout.Width(70f))) CheckPython();
            }
            EditorGUILayout.HelpBox(pythonStatus.Length > 0 ? pythonStatus : "Chưa kiểm tra", pythonOk ? MessageType.None : MessageType.Warning);
        }

        EditorGUILayout.Space(4);
        using (new EditorGUILayout.HorizontalScope())
        {
            bool can = !busy && pythonOk && File.Exists(osmPath) && Slug().Length > 0;
            using (new EditorGUI.DisabledScope(!can))
                if (GUILayout.Button("Generate", GUILayout.Height(30f))) Generate();
            if (busy && stage == Stage.Pipeline && GUILayout.Button("Huỷ", GUILayout.Height(30f), GUILayout.Width(70f))) Cancel();
        }
        if (!busy && !File.Exists(osmPath) && osmPath.Length > 0) EditorGUILayout.HelpBox("Không thấy file: " + osmPath, MessageType.Warning);

        if (busy)
        {
            var r = EditorGUILayout.GetControlRect(false, 18f);
            float t = (float)((EditorApplication.timeSinceStartup * 0.4) % 1.0);
            EditorGUI.ProgressBar(r, stage == Stage.Pipeline ? 0.1f + 0.3f * t : 0.5f,
                stage == Stage.Pipeline ? "Bước 1/2: pipeline OSM (Python)  " + (DateTime.Now - started).TotalSeconds.ToString("F0") + " s" : "Bước 2/2: dựng trong Unity");
        }
        if (lastLine.Length > 0) EditorGUILayout.LabelField(lastLine, EditorStyles.miniLabel);

        logScroll = EditorGUILayout.BeginScrollView(logScroll, GUILayout.ExpandHeight(true));
        EditorGUILayout.SelectableLabel(log.ToString(), EditorStyles.textArea, GUILayout.ExpandHeight(true), GUILayout.MinHeight(120f));
        EditorGUILayout.EndScrollView();
    }

    void DropZone()
    {
        var r = GUILayoutUtility.GetRect(0f, 54f, GUILayout.ExpandWidth(true));
        GUI.Box(r, "Kéo thả file .osm vào đây", EditorStyles.helpBox);
        var e = Event.current;
        if ((e.type == EventType.DragUpdated || e.type == EventType.DragPerform) && r.Contains(e.mousePosition))
        {
            var osm = DragAndDrop.paths.FirstOrDefault(p => p.EndsWith(".osm", StringComparison.OrdinalIgnoreCase));
            DragAndDrop.visualMode = osm != null ? DragAndDropVisualMode.Copy : DragAndDropVisualMode.Rejected;
            if (e.type == EventType.DragPerform && osm != null)
            {
                DragAndDrop.AcceptDrag();
                SetOsm(Path.GetFullPath(osm));
            }
            e.Use();
        }
    }

    // ------------------------------------------------------------------ run
    void Generate()
    {
        string slug = Slug();
        target = CityTarget.Area(slug);
        if (!EditorSceneManager.SaveCurrentModifiedScenesIfUserWantsTo()) return;
        if (AssetDatabase.IsValidFolder(target.dir))
        {
            int pick = EditorUtility.DisplayDialogComplex("Khu vực đã có",
                $"{target.dir} đã tồn tại.\n\nThay mới: xoá hết và dựng lại (mất chỉnh sửa tay).\nGiữ: đặt lại nhà, nhưng nhà đã khoá hoặc thêm tay vẫn được giữ.",
                "Thay mới", "Huỷ", "Giữ");
            if (pick == 1) return;
            if (pick == 0)
            {
                if (!AssetDatabase.DeleteAsset(target.dir)) { Log("Không xoá được " + target.dir); return; }
            }
        }

        log.Clear();
        errorsSeen = 0;
        started = DateTime.Now;
        string outDir = Path.GetFullPath(Path.Combine(MapDir, "out_" + slug));
        var args = new StringBuilder($"-u \"{Path.Combine(MapDir, "osm_pipeline.py")}\" \"{osmPath}\" --out \"{outDir}\"");
        if (!trees) args.Append(" --no-trees");
        if (!motos) args.Append(" --no-motos");
        if (!props) args.Append(" --no-props");
        Log($"> {python} {args}");

        var psi = new ProcessStartInfo(python, args.ToString())
        {
            WorkingDirectory = MapDir, UseShellExecute = false, CreateNoWindow = true,
            RedirectStandardOutput = true, RedirectStandardError = true,
            StandardOutputEncoding = Encoding.UTF8, StandardErrorEncoding = Encoding.UTF8,
        };
        psi.EnvironmentVariables["PYTHONIOENCODING"] = "utf-8";
        psi.EnvironmentVariables["PYTHONUTF8"] = "1";
        try
        {
            proc = new Process { StartInfo = psi, EnableRaisingEvents = true };
            proc.OutputDataReceived += (s, e) => { if (e.Data != null) lines.Enqueue(e.Data); };
            proc.ErrorDataReceived += (s, e) => { if (e.Data != null) lines.Enqueue(e.Data); };
            proc.Start();
            proc.BeginOutputReadLine();
            proc.BeginErrorReadLine();
            stage = Stage.Pipeline;
        }
        catch (Exception ex)
        {
            Log("Không chạy được Python: " + ex.Message);
            proc = null;
        }
    }

    void Cancel()
    {
        Kill();
        stage = Stage.Idle;
        Log("Đã huỷ.");
        Repaint();
    }

    void Kill()
    {
        try { if (proc != null && !proc.HasExited) proc.Kill(); } catch { }
        proc = null;
    }

    void Tick()
    {
        if (stage != Stage.Pipeline) return;
        bool got = false;
        while (lines.TryDequeue(out var l)) { Log(l); got = true; }
        if (proc != null && proc.HasExited)
        {
            proc.WaitForExit();                              // flush the async readers
            while (lines.TryDequeue(out var l)) Log(l);
            int code = proc.ExitCode;
            proc = null;
            if (code != 0) { stage = Stage.Idle; Log($"Pipeline lỗi (exit {code}). Xem log ở trên."); Repaint(); return; }
            stage = Stage.Unity;
            Repaint();
            EditorApplication.delayCall += RunUnity;         // let the window repaint "step 2" first
            return;
        }
        if (got || stage == Stage.Pipeline) Repaint();
    }

    /// Batch check of the Unity half after `osm_pipeline.py ... --out Map/out_<slug>`:
    /// Unity.exe -batchmode -quit -projectPath Unity -executeMethod CityGenerator.RunBatch -area <slug>
    public static void RunBatch()
    {
        var args = Environment.GetCommandLineArgs();
        int i = Array.IndexOf(args, "-area");
        var g = CreateInstance<CityGenerator>();
        g.target = CityTarget.Area(args[i + 1]);
        g.openAfter = false;
        g.started = DateTime.Now;
        g.RunUnity();
        Debug.Log(g.log.ToString());
        if (g.errorsSeen == 0 && Array.IndexOf(args, "-shots") >= 0 && File.Exists(Path.Combine(HanoiSetup.ProjectDir, g.target.dir, "Flyovers.unity")))
            FlyoverTest.ShotsF3(g.target, g.target.name + "_fly_");
        if (g.errorsSeen > 0) EditorApplication.Exit(1);
    }

    void RunUnity()
    {
        Application.LogCallback hook = (msg, st, type) =>
        {
            if (type == LogType.Error || type == LogType.Exception || type == LogType.Assert) { errorsSeen++; Log("[Unity] " + msg); }
        };
        Application.logMessageReceived += hook;
        try
        {
            if (!File.Exists(Path.GetFullPath(Path.Combine(HanoiSetup.ProjectDir, target.json))))
            {
                Log("Không thấy city.json sau pipeline.");
                return;
            }
            Directory.CreateDirectory(Path.Combine(HanoiSetup.ProjectDir, target.dir));
            AssetDatabase.Refresh();

            CityTarget.With(target, () =>
            {
                Step("Đặt nhà + mặt đất", 0.1f, () => CityPlacer.Run());
                if (hlod && errorsSeen == 0) Step("Dựng HLOD", 0.6f, () => ChunkBuilder.Run());
                if (flyovers && errorsSeen == 0)
                {
                    var (flys, _) = FlyoverBuilder.Load();
                    if (flys.Length > 0) Step($"Dựng {flys.Length} cầu vượt", 0.9f, () => FlyoverBuilder.Build());
                    else Log("Không có cầu vượt trong khu vực này.");
                }
                AssetDatabase.SaveAssets();
            });

            if (errorsSeen > 0) { Log($"Xong nhưng có {errorsSeen} lỗi, xem log."); return; }
            Log($"Xong sau {(DateTime.Now - started).TotalSeconds:F0} s: {target.dir}/{target.name}_Main.unity");
            if (openAfter) CityTarget.With(target, OpenResult);
        }
        catch (Exception ex)
        {
            Log("Lỗi: " + ex);
        }
        finally
        {
            Application.logMessageReceived -= hook;
            EditorUtility.ClearProgressBar();
            stage = Stage.Idle;
            Repaint();
        }
    }

    void Step(string label, float frac, Action a)
    {
        Log("== " + label);
        EditorUtility.DisplayProgressBar("City Generator", label, frac);
        a();
    }

    static void OpenResult()
    {
        CityPlacer.OpenAll();
        if (File.Exists(Path.Combine(HanoiSetup.ProjectDir, FlyoverBuilder.ScenePath)))
            EditorSceneManager.OpenScene(FlyoverBuilder.ScenePath, OpenSceneMode.Additive);
    }
}
