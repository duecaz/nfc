using Android.App;
using Android.Content;
using Android.Content.PM;
using Android.Nfc;
using Android.OS;
using Android.Views;
using Android.Webkit;

namespace LaNubeKiosk;

[Activity(
    Label = "@string/app_name",
    MainLauncher = true,
    LaunchMode = LaunchMode.SingleTop,
    ConfigurationChanges = ConfigChanges.Orientation | ConfigChanges.KeyboardHidden | ConfigChanges.ScreenSize)]
public class MainActivity : Activity
{
    private WebView webView = null!;
    private NfcAdapter? nfcAdapter;
    private IValueCallback? filePathCallback;
    private DownloadReceiver? _downloadReceiver;
    private readonly System.Collections.Generic.HashSet<long> _activeDownloads = new();
    private int _sessionGen;   // invalida timers de sesión previos

    private const string KioskUrl       = "https://lanube.uno";
    private const string LogTag         = "LaNubeKiosk";
    private const string ApkVersion     = "7";
    private const int    FileChooserCode = 1001;

    protected override void OnCreate(Bundle? savedInstanceState)
    {
        base.OnCreate(savedInstanceState);
        Window!.AddFlags(WindowManagerFlags.KeepScreenOn);

        webView = new WebView(this);
        SetContentView(webView);

        CookieManager.Instance?.SetAcceptCookie(true);
        CookieManager.Instance?.SetAcceptThirdPartyCookies(webView, true);

        webView.Settings!.JavaScriptEnabled = true;
        webView.Settings.DomStorageEnabled = true;
        webView.Settings.SetSupportZoom(false);
        webView.Settings.BuiltInZoomControls = false;
        webView.Settings.DisplayZoomControls = false;
        webView.Settings.UseWideViewPort = true;
        webView.Settings.LoadWithOverviewMode = true;
        webView.Settings.JavaScriptCanOpenWindowsAutomatically = true;
        webView.Settings.SetSupportMultipleWindows(true);
        webView.SetWebViewClient(new KioskWebViewClient(this));
        webView.SetWebChromeClient(new KioskWebChromeClient(this));
        webView.SetDownloadListener(new KioskDownloadListener(this));
        webView.AddJavascriptInterface(new KioskJsBridge(this), "AndroidKiosk");
        webView.LoadUrl(KioskUrl);

        nfcAdapter = NfcAdapter.GetDefaultAdapter(this);
        NfcKit.Init(this);  // I2C panel NFC (Amlogic/Droidlogic)
        Android.Util.Log.Debug(LogTag, $"APK v{ApkVersion} iniciado. NFC-std: {(nfcAdapter != null ? "OK" : "NO")}");

        _downloadReceiver = new DownloadReceiver(this);
        var dlFilter = new IntentFilter(DownloadManager.ActionDownloadComplete);
#pragma warning disable CA1416
        if (Build.VERSION.SdkInt >= BuildVersionCodes.Tiramisu)
            RegisterReceiver(_downloadReceiver, dlFilter, ReceiverFlags.Exported);
        else
            RegisterReceiver(_downloadReceiver, dlFilter);
#pragma warning restore CA1416

        HideSystemUI();
    }

    protected override void OnDestroy()
    {
        base.OnDestroy();
        CancelSessionTimer();
        if (_downloadReceiver != null)
        {
            UnregisterReceiver(_downloadReceiver);
            _downloadReceiver = null;
        }
    }

    // ---- Timer nativo de sesión (cierre garantizado, sobrevive a la navegación) ----
    // Lo dispara la web al autenticar: AndroidKiosk.startSession(minutos).
    public void StartSessionTimer(int minutes)
    {
        int gen = ++_sessionGen;   // invalida cualquier timer anterior
        Android.Util.Log.Debug(LogTag, $"Sesión: timer {minutes} min (gen {gen})");
        if (minutes <= 0) return;
        new Handler(Looper.MainLooper!).PostDelayed(() =>
        {
            if (gen != _sessionGen) return;   // reemplazado por otra sesión / cancelado
            Android.Util.Log.Debug(LogTag, "Sesión expirada -> logout");
            webView.LoadUrl(KioskUrl + "/logout");
        }, (long)minutes * 60_000L);
    }

    public void CancelSessionTimer() => _sessionGen++;

    // Puente JS: expone AndroidKiosk.startSession(minutos) a la web del kiosko.
    private class KioskJsBridge : Java.Lang.Object
    {
        private readonly MainActivity _host;
        public KioskJsBridge(MainActivity host) => _host = host;

        [Android.Webkit.JavascriptInterface]
        [Java.Interop.Export("startSession")]
        public void StartSession(int minutes)
            => _host.RunOnUiThread(() => _host.StartSessionTimer(minutes));
    }

    public override void OnWindowFocusChanged(bool hasFocus)
    {
        base.OnWindowFocusChanged(hasFocus);
        if (hasFocus) HideSystemUI();
    }

    private void HideSystemUI()
    {
#pragma warning disable CA1416, CS0618
        Window!.DecorView.SystemUiVisibility = (StatusBarVisibility)(
            (int)SystemUiFlags.Fullscreen |
            (int)SystemUiFlags.HideNavigation |
            (int)SystemUiFlags.ImmersiveSticky |
            (int)SystemUiFlags.LayoutStable |
            (int)SystemUiFlags.LayoutHideNavigation |
            (int)SystemUiFlags.LayoutFullscreen);
#pragma warning restore CA1416, CS0618
    }

    protected override void OnResume()
    {
        base.OnResume();

        // Standard Android NFC (USB readers, regular phones/tablets)
        if (nfcAdapter != null)
        {
            var intent = new Intent(this, typeof(MainActivity));
            intent.AddFlags(ActivityFlags.SingleTop);
#pragma warning disable CA1416
            var flags = Build.VERSION.SdkInt >= BuildVersionCodes.S
                ? PendingIntentFlags.Mutable
                : (PendingIntentFlags)0;
#pragma warning restore CA1416
            var pending = PendingIntent.GetActivity(this, 0, intent, flags);
            nfcAdapter.EnableForegroundDispatch(this, pending, null, null);
        }

        // I2C panel NFC (Amlogic/Droidlogic panels with built-in NFC reader)
        NfcKit.Register(uid => RunOnUiThread(() =>
            webView.EvaluateJavascript(
                $"if(typeof authenticate==='function')authenticate('{uid}')", null)));
        NfcKit.StartReadJob();
    }

    protected override void OnPause()
    {
        base.OnPause();
        nfcAdapter?.DisableForegroundDispatch(this);
        NfcKit.StopReadJob();
        NfcKit.Unregister();
    }

    protected override void OnNewIntent(Intent? intent)
    {
        base.OnNewIntent(intent);
        if (intent == null) return;
        try
        {
#pragma warning disable CA1422
            var tagObj = intent.GetParcelableExtra(NfcAdapter.ExtraTag);
#pragma warning restore CA1422
            if (tagObj is not Android.Nfc.Tag tag) return;
            var id = tag.GetId();
            if (id == null || id.Length == 0) return;
            var raw = BitConverter.ToString(id).Replace("-", "");
            Array.Reverse(id);
            var sb = new System.Text.StringBuilder();
            foreach (var b in id)
                sb.Append(((b & 0x0F) << 4 | (b >> 4)).ToString("X2"));
            var uid = sb.ToString();
            Android.Util.Log.Debug(LogTag, $"NFC RAW={raw} UID={uid}");
            webView.EvaluateJavascript($"if(typeof authenticate==='function')authenticate('{uid}')", null);
        }
        catch (Exception ex)
        {
            Android.Util.Log.Error(LogTag, $"NFC error: {ex.Message}");
        }
    }

    protected override void OnActivityResult(int requestCode, Result resultCode, Intent? data)
    {
        base.OnActivityResult(requestCode, resultCode, data);
        if (requestCode != FileChooserCode)
        {
            filePathCallback?.OnReceiveValue(null);
            filePathCallback = null;
            return;
        }
        Android.Net.Uri[]? results = null;
        if (resultCode == Result.Ok && data?.Data != null)
            results = new[] { data.Data };
        filePathCallback?.OnReceiveValue(results);
        filePathCallback = null;
    }

    public override void OnBackPressed()
    {
        if (webView.CanGoBack()) webView.GoBack();
    }

    // ---- Apertura automática al terminar la descarga ----
    private class DownloadReceiver : BroadcastReceiver
    {
        private readonly MainActivity _host;
        public DownloadReceiver(MainActivity host) => _host = host;

        public override void OnReceive(Context? context, Intent? intent)
        {
            var id = intent?.GetLongExtra(DownloadManager.ExtraDownloadId, -1) ?? -1;
            if (id == -1 || !_host._activeDownloads.Remove(id)) return;

            var dm = (DownloadManager?)_host.GetSystemService(DownloadService);
            if (dm == null) return;

            var query = new DownloadManager.Query();
            query.SetFilterById(id);
            var cursor = dm.InvokeQuery(query);
            if (cursor == null || !cursor.MoveToFirst()) { cursor?.Close(); return; }

            var statusIdx   = cursor.GetColumnIndex(DownloadManager.ColumnStatus);
            var mimeIdx     = cursor.GetColumnIndex("media_type");
            var localUriIdx = cursor.GetColumnIndex(DownloadManager.ColumnLocalUri);
            var status      = (DownloadStatus)cursor.GetInt(statusIdx);
            var mime        = (mimeIdx >= 0 ? cursor.GetString(mimeIdx) : null) ?? "*/*";
            var localUriStr = localUriIdx >= 0 ? cursor.GetString(localUriIdx) : null;
            cursor.Close();

            if (status != DownloadStatus.Successful) return;
            try
            {
                Android.Net.Uri? contentUri = null;

                if (!string.IsNullOrEmpty(localUriStr))
                {
                    var localPath = Android.Net.Uri.Parse(localUriStr)?.Path;
                    if (!string.IsNullOrEmpty(localPath))
                    {
                        var javaFile = new Java.IO.File(localPath);
                        if (javaFile.Exists())
                        {
                            contentUri = AndroidX.Core.Content.FileProvider.GetUriForFile(
                                _host, "uno.lanube.kiosk.fileprovider", javaFile);
                        }
                    }
                }

                if (contentUri == null)
                {
                    var baseUri = Android.Net.Uri.Parse("content://downloads/public_downloads");
                    if (baseUri != null)
                        contentUri = ContentUris.WithAppendedId(baseUri, id);
                }
                if (contentUri == null) return;

                var openIntent = new Intent(Intent.ActionView)
                    .SetDataAndType(contentUri, mime)
                    .SetFlags(ActivityFlags.NewTask |
                              ActivityFlags.GrantReadUriPermission |
                              ActivityFlags.GrantWriteUriPermission);
                _host.StartActivity(openIntent);
                Android.Util.Log.Debug(LogTag, $"Abriendo descarga id={id} uri={contentUri} ({mime})");
            }
            catch (Exception ex)
            {
                Android.Util.Log.Error(LogTag, $"Open file error: {ex.Message}");
                try
                {
                    _host.StartActivity(
                        new Intent(DownloadManager.ActionViewDownloads)
                            .SetFlags(ActivityFlags.NewTask));
                }
                catch { }
            }
        }
    }

    // ---- Descarga de archivos con cookies de sesión ----
    private class KioskDownloadListener : Java.Lang.Object, IDownloadListener
    {
        private readonly MainActivity _host;
        public KioskDownloadListener(MainActivity host) => _host = host;

        public void OnDownloadStart(
            string? url, string? userAgent,
            string? contentDisposition, string? mimetype, long contentLength)
        {
            if (url == null) return;
            try
            {
                var fileName = URLUtil.GuessFileName(url, contentDisposition, mimetype ?? "*/*");
                var cookies  = CookieManager.Instance?.GetCookie(url) ?? "";

                var req = new DownloadManager.Request(Android.Net.Uri.Parse(url));
                req.SetMimeType(mimetype);
                req.AddRequestHeader("Cookie", cookies);
                req.AddRequestHeader("User-Agent", userAgent);
                req.SetTitle(fileName);
                req.SetDescription("La Nube — descargando");
                req.SetNotificationVisibility(DownloadVisibility.VisibleNotifyCompleted);
                req.SetDestinationInExternalPublicDir(
                    Android.OS.Environment.DirectoryDownloads, fileName);

                var dm = (DownloadManager?)_host.GetSystemService(DownloadService);
                var downloadId = dm?.Enqueue(req) ?? -1;
                if (downloadId > 0) _host._activeDownloads.Add(downloadId);

                Android.Widget.Toast.MakeText(
                    _host, $"Descargando {fileName}…",
                    Android.Widget.ToastLength.Long)?.Show();

                Android.Util.Log.Debug(LogTag, $"Download: {fileName} (id={downloadId})");
            }
            catch (Exception ex)
            {
                Android.Util.Log.Error(LogTag, $"Download error: {ex.Message}");
            }
        }
    }

    // ---- WebView client: sesión expirada + notificaciones + caché + red ----
    private class KioskWebViewClient : WebViewClient
    {
        private readonly MainActivity _host;
        public KioskWebViewClient(MainActivity host) => _host = host;

        public override bool ShouldOverrideUrlLoading(WebView? view, IWebResourceRequest? request)
        {
            var url = request?.Url?.ToString() ?? "";
            if (url.Contains("/app/login") || url.Contains("index.php/login"))
            {
                Android.Util.Log.Warn(LogTag, "Sesión NC expirada, volviendo al kiosko");
                view?.LoadUrl(KioskUrl);
                return true;
            }
            return false;
        }

        public override void OnPageFinished(WebView? view, string? url)
        {
            base.OnPageFinished(view, url);

            view?.EvaluateJavascript("document.getElementById('catcher')?.focus()", null);

            view?.EvaluateJavascript(
                "(function(){if('Notification' in window){" +
                "try{Object.defineProperty(Notification,'permission',{get:()=>'denied',configurable:true});}catch(e){}" +
                "Notification.requestPermission=function(){return Promise.resolve('denied');};}})()", null);

            if (url == KioskUrl || url == KioskUrl + "/")
            {
                view?.EvaluateJavascript(
                    "(function(){var e=document.getElementById('_apkv');" +
                    "if(!e){e=document.createElement('span');e.id='_apkv';" +
                    "e.style.cssText='position:fixed;bottom:.5rem;left:3.6rem;font-size:.6rem;color:#d1d5db;pointer-events:none';" +
                    $"document.body.appendChild(e);}}e.textContent='apk v{ApkVersion}';}})();", null);

                view?.ClearCache(true);
                view?.ClearHistory();
                _host.CancelSessionTimer();   // en el kiosko (login) no hay sesión activa
                Android.Util.Log.Debug(LogTag, "Sesión cerrada: caché e historial limpiados");
            }
        }

        public override void OnReceivedError(
            WebView? view, IWebResourceRequest? request, WebResourceError? error)
        {
            if (request?.IsForMainFrame != true) return;
#pragma warning disable CA1416
            Android.Util.Log.Warn(LogTag, $"Error red: {error?.Description}");
#pragma warning restore CA1416
            view?.PostDelayed(() => view.LoadUrl(KioskUrl), 5000);
        }
    }

    // ---- Popup/nueva-ventana: carga en el WebView principal ----
    private class PopupRedirectClient : WebViewClient
    {
        private readonly WebView _mainView;
        public PopupRedirectClient(WebView mainView) => _mainView = mainView;

        public override void OnPageStarted(WebView? view, string? url, Android.Graphics.Bitmap? favicon)
        {
            if (!string.IsNullOrEmpty(url) && !url.StartsWith("about:"))
            {
                Android.Util.Log.Debug(LogTag, $"Popup redirigido: {url}");
                _mainView.LoadUrl(url);
            }
            view?.StopLoading();
        }
    }

    // ---- ChromeClient: subida de archivos + ventanas emergentes + permisos ----
    private class KioskWebChromeClient : WebChromeClient
    {
        private readonly MainActivity _host;
        public KioskWebChromeClient(MainActivity host) => _host = host;

        public override bool OnCreateWindow(WebView? view, bool isDialog, bool isUserGesture, Android.OS.Message? resultMsg)
        {
            if (resultMsg?.Obj is WebView.WebViewTransport transport)
            {
                var popup = new WebView(view!.Context!);
                popup.SetWebViewClient(new PopupRedirectClient(_host.webView));
                transport.WebView = popup;
                resultMsg.SendToTarget();
                return true;
            }
            return false;
        }

        public override bool OnShowFileChooser(
            WebView? webView,
            IValueCallback? filePathCallback,
            FileChooserParams? fileChooserParams)
        {
            _host.filePathCallback?.OnReceiveValue(null);
            _host.filePathCallback = filePathCallback;
            try
            {
                var intent = fileChooserParams?.CreateIntent()
                    ?? new Intent(Intent.ActionOpenDocument).SetType("*/*");
                _host.StartActivityForResult(
                    Intent.CreateChooser(intent, "Seleccionar archivo"),
                    FileChooserCode);
            }
            catch (Exception ex)
            {
                Android.Util.Log.Error(LogTag, $"FileChooser error: {ex.Message}");
                _host.filePathCallback?.OnReceiveValue(null);
                _host.filePathCallback = null;
            }
            return true;
        }

        public override void OnPermissionRequest(PermissionRequest? request)
        {
            request?.Grant(request.GetResources());
        }
    }
}
