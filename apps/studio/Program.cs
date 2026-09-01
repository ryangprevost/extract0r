// Extract0r Studio - a self-contained front end for the FastAPI service.
//
// Two jobs, both small:
//   1. Serve wwwroot/index.html, which is the entire UI.
//   2. Reverse-proxy /api/* to the Python service.
//
// The proxy is the important part. It puts the UI and the API on one origin, so the
// browser never makes a cross-origin request and CORS stops mattering at all. It is the
// same trick apps/web/next.config.ts uses with `rewrites`, so both front ends talk to
// the API identically.

using System.Net;

var builder = WebApplication.CreateBuilder(args);

// Note the literal 127.0.0.1 rather than "localhost". On Windows, localhost resolves to
// ::1 before 127.0.0.1, and uvicorn bound to 127.0.0.1 is not listening on ::1 - so every
// proxied request paid a ~2 second connect timeout before falling back to IPv4. Measured
// in this app's own logs: 2054 ms for a call that takes 4 ms once the address is explicit.
var apiOrigin = builder.Configuration["ApiOrigin"] ?? "http://127.0.0.1:8000";

// Uploads are audio files. The API caps them at MAX_UPLOAD_MB (60 by default); Kestrel
// must not reject them first with its own 30 MB default.
builder.WebHost.ConfigureKestrel(options => options.Limits.MaxRequestBodySize = 256 * 1024 * 1024);

builder.Services.AddHttpClient("api", client =>
{
    client.BaseAddress = new Uri(apiOrigin);
    // Separation jobs return 202 immediately, so requests are short - but model loading
    // can stall the very first one. Generous rather than clever.
    client.Timeout = TimeSpan.FromMinutes(10);
}).ConfigurePrimaryHttpMessageHandler(() => new SocketsHttpHandler
{
    AllowAutoRedirect = false,
    UseCookies = false,
});

var app = builder.Build();

app.UseDefaultFiles();

// Always revalidate wwwroot assets.
//
// Without an explicit Cache-Control, ASP.NET sends only an ETag and browsers fall back to
// heuristic caching - they may reuse a stale copy without asking. That bites hard here,
// because index.html and app.js are edited together: a cached app.js against a fresh
// index.html means the script looks up elements that no longer exist and dies with
// "Cannot set properties of null". `no-cache` still allows a 304, so this costs one
// conditional request per file, not a re-download.
app.UseStaticFiles(new StaticFileOptions
{
    OnPrepareResponse = ctx =>
    {
        ctx.Context.Response.Headers.CacheControl = "no-cache, must-revalidate";
    },
});

app.Map("/api/{**path}", ProxyToApi);

// A friendly failure is better than a wall of proxy exception text: the Python service
// not running is by far the most likely reason this page misbehaves.
app.MapGet("/studio/status", async (IHttpClientFactory factory) =>
{
    try
    {
        var client = factory.CreateClient("api");
        var response = await client.GetAsync("/api/v1/health");
        return Results.Json(new
        {
            apiOrigin,
            reachable = response.IsSuccessStatusCode,
            status = (int)response.StatusCode,
        });
    }
    catch (Exception ex)
    {
        return Results.Json(new { apiOrigin, reachable = false, error = ex.Message });
    }
});

app.Run();

static async Task ProxyToApi(HttpContext context, IHttpClientFactory factory)
{
    var client = factory.CreateClient("api");
    var target = new Uri(client.BaseAddress!, context.Request.Path + context.Request.QueryString);

    using var request = new HttpRequestMessage(new HttpMethod(context.Request.Method), target);

    // Only attach a body when there is one; GET with a StreamContent upsets some servers.
    if (context.Request.ContentLength is > 0 || context.Request.Headers.ContainsKey("Transfer-Encoding"))
    {
        request.Content = new StreamContent(context.Request.Body);
    }

    foreach (var header in context.Request.Headers)
    {
        // Host must be the target's, not ours, and the request-header collection rejects
        // content headers - hence the fallback onto request.Content.
        if (string.Equals(header.Key, "Host", StringComparison.OrdinalIgnoreCase)) continue;
        if (!request.Headers.TryAddWithoutValidation(header.Key, header.Value.ToArray()))
        {
            request.Content?.Headers.TryAddWithoutValidation(header.Key, header.Value.ToArray());
        }
    }

    HttpResponseMessage response;
    try
    {
        response = await client.SendAsync(
            request, HttpCompletionOption.ResponseHeadersRead, context.RequestAborted);
    }
    catch (HttpRequestException ex)
    {
        context.Response.StatusCode = (int)HttpStatusCode.BadGateway;
        context.Response.ContentType = "application/json";
        await context.Response.WriteAsJsonAsync(new
        {
            detail = $"Could not reach the Extract0r API at {client.BaseAddress}. "
                   + "Start it with scripts/dev-api.ps1, then reload this page. "
                   + $"({ex.Message})",
        });
        return;
    }

    using (response)
    {
        context.Response.StatusCode = (int)response.StatusCode;

        foreach (var header in response.Headers)
        {
            context.Response.Headers[header.Key] = header.Value.ToArray();
        }
        foreach (var header in response.Content.Headers)
        {
            context.Response.Headers[header.Key] = header.Value.ToArray();
        }

        // Kestrel sets its own framing; leaving the upstream value corrupts the response.
        context.Response.Headers.Remove("transfer-encoding");

        await response.Content.CopyToAsync(context.Response.Body, context.RequestAborted);
    }
}
