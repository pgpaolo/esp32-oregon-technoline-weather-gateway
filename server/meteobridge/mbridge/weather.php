<?php
declare(strict_types=1);

require_once dirname(__DIR__) . '/lib/weather_realtime.php';

header('Content-Type: application/json; charset=UTF-8');
header('Cache-Control: no-store, no-cache, must-revalidate, max-age=0');
header('Pragma: no-cache');
header('X-Content-Type-Options: nosniff');
header('Referrer-Policy: no-referrer');

$stationId = weather_realtime_station_id(
    isset($_GET['station']) ? (string)$_GET['station'] : WEATHER_REALTIME_DEFAULT_STATION
);

if ($stationId === null) {
    http_response_code(400);
    echo json_encode([
        'ok' => false,
        'error' => 'invalid_station_id',
    ], JSON_UNESCAPED_SLASHES | JSON_UNESCAPED_UNICODE);
    exit;
}

$record = weather_realtime_read_station($stationId);
if (!is_array($record)) {
    http_response_code(404);
    echo json_encode([
        'ok' => false,
        'schema' => WEATHER_REALTIME_SCHEMA,
        'station_id' => $stationId,
        'error' => 'station_data_not_found',
    ], JSON_UNESCAPED_SLASHES | JSON_UNESCAPED_UNICODE);
    exit;
}

$timestamp = isset($record['timestamp']) ? (int)$record['timestamp'] : 0;
$age = $timestamp > 0 ? max(0, time() - $timestamp) : PHP_INT_MAX;

$staleAfter = isset($_GET['stale_after']) ? (int)$_GET['stale_after'] : 180;
$staleAfter = max(30, min(3600, $staleAfter));

$response = [
    'ok' => true,
    'schema' => $record['schema'] ?? WEATHER_REALTIME_SCHEMA,
    'schema_version' => $record['schema_version'] ?? 1,
    'station_id' => $stationId,
    'source' => $record['source'] ?? null,
    'timestamp' => $timestamp,
    'received_at' => $record['received_at'] ?? null,
    'age_seconds' => $age,
    'stale' => $age > $staleAfter,
    'data' => is_array($record['data'] ?? null) ? $record['data'] : [],
    'meta' => is_array($record['meta'] ?? null) ? $record['meta'] : [],
];

echo json_encode(
    $response,
    JSON_UNESCAPED_SLASHES | JSON_UNESCAPED_UNICODE | JSON_PRESERVE_ZERO_FRACTION
);
