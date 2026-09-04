<?php
declare(strict_types=1);

require_once dirname(__DIR__) . '/lib/diga_security.php';
require_once dirname(__DIR__) . '/lib/diga_storage.php';
require_once dirname(__DIR__) . '/lib/weather_realtime.php';

diga_require_public_realtime_request();

$config = diga_security_config();
$raw = $_GET['d'] ?? '';

if ((!is_string($raw) || $raw === '') && isset($_SERVER['QUERY_STRING'])) {
    $queryString = (string)$_SERVER['QUERY_STRING'];
    if (str_starts_with($queryString, 'd=') && strlen($queryString) > 2) {
        $raw = rawurldecode(str_replace('+', ' ', substr($queryString, 2)));
    }
}

if (!is_string($raw)) {
    diga_record_receiver_status(400, 'Weather data invalid', [
        'query_bytes' => strlen((string)($_SERVER['QUERY_STRING'] ?? '')),
    ]);
    diga_fail(400, 'Weather data invalid');
}

$data = trim((string)preg_replace('/[\r\n\t]+/', ' ', $raw));
$data = (string)preg_replace('/ {2,}/', ' ', $data);
$dataBytes = strlen($data);

if ($dataBytes === 0) {
    diga_record_receiver_status(400, 'Weather data missing', [
        'query_bytes' => strlen((string)($_SERVER['QUERY_STRING'] ?? '')),
        'data_bytes' => 0,
    ]);
    diga_fail(400, 'Weather data missing');
}

if ($dataBytes > (int)$config['max_realtime_bytes']) {
    diga_record_receiver_status(413, 'Weather data too large', ['data_bytes' => $dataBytes]);
    diga_fail(413, 'Weather data too large');
}

if (strpos($data, "\0") !== false) {
    diga_record_receiver_status(400, 'Weather data invalid', ['data_bytes' => $dataBytes]);
    diga_fail(400, 'Weather data invalid');
}

$unresolvedReplaced = preg_match_all('/\[[^\]]+\]/', $data);
if (is_int($unresolvedReplaced) && $unresolvedReplaced > 0) {
    $data = (string)preg_replace('/\[[^\]]+\]/', '--', $data);
}

$validation = diga_validate_realtime_packet($data);
if (empty($validation['valid'])) {
    diga_record_receiver_status(422, (string)$validation['error'], [
        'data_bytes' => $dataBytes,
        'fields' => (int)($validation['fields'] ?? 0),
    ]);
    diga_fail(422, (string)$validation['error']);
}

$stationWasExplicit = isset($_GET['station']) && trim((string)$_GET['station']) !== '';
$stationId = weather_realtime_station_id(
    $stationWasExplicit ? (string)$_GET['station'] : WEATHER_REALTIME_DEFAULT_STATION
);

if ($stationId === null) {
    diga_record_receiver_status(400, 'Invalid station id', [
        'station' => (string)($_GET['station'] ?? ''),
    ]);
    diga_fail(400, 'Invalid station id');
}

$source = weather_realtime_source_name(
    isset($_GET['source']) ? (string)$_GET['source'] : 'mb-compatible'
);

$legacyFlag = strtolower(trim((string)($_GET['legacy'] ?? '')));
$legacyWrite = !$stationWasExplicit || in_array($legacyFlag, ['1', 'true', 'yes', 'on'], true);

if ($legacyWrite) {
    if (!diga_realtime_store(
        $data,
        $validation,
        is_int($unresolvedReplaced) ? $unresolvedReplaced : 0
    )) {
        diga_record_receiver_status(500, 'Unable to store legacy weather data', [
            'data_bytes' => $dataBytes,
            'station' => $stationId,
        ]);
        diga_fail(500, 'Unable to store legacy weather data');
    }
}

if (!weather_realtime_store_mb($data, $stationId, $source, $validation)) {
    diga_record_receiver_status(500, 'Unable to store normalized weather data', [
        'data_bytes' => $dataBytes,
        'station' => $stationId,
    ]);
    diga_fail(500, 'Unable to store normalized weather data');
}

$archiveInfo = function_exists('diga_archive_last_write_info')
    ? diga_archive_last_write_info()
    : [];

diga_record_receiver_status(200, 'success', [
    'data_bytes' => $dataBytes,
    'fields' => (int)$validation['fields'],
    'missing' => (int)$validation['missing'],
    'numeric' => (int)$validation['numeric'],
    'unresolved_replaced' => is_int($unresolvedReplaced) ? $unresolvedReplaced : 0,
    'storage' => $legacyWrite ? diga_realtime_backend() : 'normalized-only',
    'station' => $stationId,
    'source' => $source,
    'normalized_schema' => WEATHER_REALTIME_SCHEMA,
    'legacy_write' => $legacyWrite,
    'archive' => $legacyWrite && function_exists('diga_archive_last_write_status')
        ? diga_archive_last_write_status()
        : 'not-requested',
    'archive_bucket_end' => $legacyWrite ? ($archiveInfo['bucket_end'] ?? null) : null,
    'archive_samples' => $legacyWrite ? ($archiveInfo['samples'] ?? null) : null,
    'archive_time_source' => $legacyWrite ? ($archiveInfo['time_source'] ?? null) : null,
    'archive_clock_skew' => $legacyWrite ? ($archiveInfo['clock_skew'] ?? null) : null,
]);

header('Content-Type: text/plain; charset=UTF-8');
echo 'success';
