// Defaults preserve the original bare-metal behaviour (127.0.0.1 + fixed ports);
// containers override the bind hosts via WS_*_HOST (see Dockerfile/docker-compose.yml).
function env(name, fallback) {
    return process.env[name] !== undefined ? process.env[name] : fallback;
}

module.exports = {
    get_host: env('WS_GET_HOST', '127.0.0.1'),
    get_port: +env('WS_GET_PORT', 15100),
    post_host: env('WS_POST_HOST', '127.0.0.1'),
    post_port: +env('WS_POST_PORT', 15101),
    http_host: env('WS_HTTP_HOST', '127.0.0.1'),
    http_port: +env('WS_HTTP_PORT', 15102),
    long_poll_timeout: +env('WS_LONG_POLL_TIMEOUT', 29000),
};
