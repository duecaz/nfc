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

    private const string KioskUrl = "https://lanube.uno";
    private const string LogTag = "LaNubeKiosk";
    private const int FileChooserCode = 1001;

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
        webView.LoadUrl(KioskUrl);

        nfcAdapter = NfcAdapter.GetDefaultAdapter(this);
        Android.Util.Log.Debug(LogTag, $"Iniciado. NFC: {(nfcAdapter != null ? "OK" : "NO")}");
        HideSystemUI();
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
        if (nfcAdapter == null) return;
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

    protected override void OnPause()
    {
        base.OnPause();
        nfcAdapter?.DisableForegroundDispatch(this);
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
                dm?.Enqueue(req);

                Android.Widget.Toast.MakeText(
                    _host, $"Descargando {fileName}…",
                    Android.Widget.ToastLength.Long)?.Show();

                Android.Util.Log.Debug(LogTag, $"Download: {fileName}");
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

            // Rechazar silenciosamente el permiso de notificaciones de NC
            view?.EvaluateJavascript(
                "(function(){" +
                "if('Notification' in window){" +
                "try{Object.defineProperty(Notification,'permission',{get:()=>'denied',configurable:true});}catch(e){}" +
                "Notification.requestPermission=function(){return Promise.resolve('denied');};}" +
                "})()", null);

            // Al volver al kiosko (fin de sesión): limpiar caché HTTP e historial
            if (url == KioskUrl || url == KioskUrl + "/")
            {
                view?.ClearCache(true);
                view?.ClearHistory();
                Android.Util.Log.Debug(LogTag, "Sesión cerrada: caché e historial limpiados");
            }
        }

        public override void OnReceivedError(
            WebView? view, IWebResourceRequest? request, WebResourceError? error)
        {
            if (request?.IsForMainFrame != true) return;
            Android.Util.Log.Warn(LogTag, $"Error red: {error?.Description}");
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
