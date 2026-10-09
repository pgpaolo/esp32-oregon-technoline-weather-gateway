<?php
declare(strict_types=1);

/*
 * Weather Realtime API v1
 *
 * Normalizza un pacchetto Meteobridge/Aurora-compatible in un JSON canonico,
 * separato per station_id. Nessun dato mancante viene rappresentato con "--"
 * nel JSON: i valori assenti diventano null.
 */

const WEATHER_REALTIME_SCHEMA = 'weather-realtime-v1';
const WEATHER_REALTIME_DEFAULT_STATION = 'legacy-primary';
const WEATHER_REALTIME_MAX_STATION_LEN = 64;

function weather_realtime_base_dir(): string
{
    $configured = getenv('WEATHER_REALTIME_DIR');
    $dir = is_string($configured) && $configured !== ''
        ? rtrim($configured, '/')
        : '/var/tmp/weather-realtime';

    if (!is_dir($dir)) {
        @mkdir($dir, 0770, true);
    }
    return $dir;
}

function weather_realtime_station_id(?string $value): ?string
{
    $value = trim((string)$value);
    if ($value === '') {
        return WEATHER_REALTIME_DEFAULT_STATION;
    }
    if (strlen($value) > WEATHER_REALTIME_MAX_STATION_LEN) {
        return null;
    }
    if (!preg_match('/^[A-Za-z0-9][A-Za-z0-9._-]*$/', $value)) {
        return null;
    }
    return $value;
}

function weather_realtime_source_name(?string $value): string
{
    $value = trim((string)$value);
    if ($value === '') {
        return 'mb-compatible';
    }
    if (strlen($value) > 32 || !preg_match('/^[A-Za-z0-9._-]+$/', $value)) {
        return 'mb-compatible';
    }
    return $value;
}

function weather_realtime_current_file(string $stationId): string
{
    return weather_realtime_base_dir() . '/' . $stationId . '.json';
}

function weather_realtime_stats_file(string $stationId): string
{
    return weather_realtime_base_dir() . '/' . $stationId . '.daily.json';
}

function weather_realtime_atomic_write_json(string $path, array $payload): bool
{
    $dir = dirname($path);
    if (!is_dir($dir) && !@mkdir($dir, 0770, true) && !is_dir($dir)) {
        return false;
    }

    $json = json_encode(
        $payload,
        JSON_UNESCAPED_SLASHES | JSON_UNESCAPED_UNICODE | JSON_PRESERVE_ZERO_FRACTION
    );
    if (!is_string($json)) {
        return false;
    }

    $tmp = $path . '.tmp.' . bin2hex(random_bytes(4));
    $ok = @file_put_contents($tmp, $json . PHP_EOL, LOCK_EX);
    if ($ok === false) {
        @unlink($tmp);
        return false;
    }
    @chmod($tmp, 0660);
    if (!@rename($tmp, $path)) {
        @unlink($tmp);
        return false;
    }
    return true;
}

function weather_realtime_token(array $fields, int $index): ?string
{
    if (!array_key_exists($index, $fields)) {
        return null;
    }
    $value = trim((string)$fields[$index]);
    if ($value === '' || $value === '--' || $value === '-' || $value === 'null' || $value === 'NULL') {
        return null;
    }
    return $value;
}

function weather_realtime_number(array $fields, int $index): ?float
{
    $value = weather_realtime_token($fields, $index);
    if ($value === null) {
        return null;
    }

    if (str_contains($value, ',') && !str_contains($value, '.')) {
        $value = str_replace(',', '.', $value);
    }
    if (!is_numeric($value)) {
        return null;
    }

    $number = (float)$value;
    return is_finite($number) ? $number : null;
}

function weather_realtime_cardinal(?float $degrees): ?string
{
    if ($degrees === null) {
        return null;
    }
    $normalized = fmod($degrees, 360.0);
    if ($normalized < 0) {
        $normalized += 360.0;
    }
    $names = [
        'N','NNE','NE','ENE','E','ESE','SE','SSE',
        'S','SSW','SW','WSW','W','WNW','NW','NNW'
    ];
    $index = (int)floor(($normalized + 11.25) / 22.5) % 16;
    return $names[$index];
}

function weather_realtime_read_json_file(string $path): ?array
{
    if (!is_file($path) || !is_readable($path)) {
        return null;
    }
    $raw = @file_get_contents($path);
    if (!is_string($raw) || $raw === '') {
        return null;
    }
    $decoded = json_decode($raw, true);
    return is_array($decoded) ? $decoded : null;
}

function weather_realtime_update_daily_stats(string $stationId, array $data, int $now): array
{
    $day = date('Y-m-d', $now);
    $path = weather_realtime_stats_file($stationId);
    $stats = weather_realtime_read_json_file($path);

    if (!is_array($stats) || ($stats['day'] ?? '') !== $day) {
        $stats = [
            'day' => $day,
            'temperature_min_c' => null,
            'temperature_max_c' => null,
            'pressure_min_hpa' => null,
            'pressure_max_hpa' => null,
            'wind_speed_max_kmh' => null,
            'wind_gust_max_kmh' => null,
            'rain_rate_max_mmh' => null,
            'uv_max' => null,
            'updated_at' => $now,
        ];
    }

    $minMap = [
        'temperature_c' => 'temperature_min_c',
        'pressure_hpa' => 'pressure_min_hpa',
    ];
    foreach ($minMap as $dataKey => $statsKey) {
        $value = $data[$dataKey] ?? null;
        if (is_int($value) || is_float($value)) {
            $current = $stats[$statsKey] ?? null;
            $stats[$statsKey] = $current === null ? $value : min((float)$current, (float)$value);
        }
    }

    $maxMap = [
        'temperature_c' => 'temperature_max_c',
        'pressure_hpa' => 'pressure_max_hpa',
        'wind_speed_kmh' => 'wind_speed_max_kmh',
        'wind_gust_kmh' => 'wind_gust_max_kmh',
        'rain_rate_mmh' => 'rain_rate_max_mmh',
        'uv_index' => 'uv_max',
    ];
    foreach ($maxMap as $dataKey => $statsKey) {
        $value = $data[$dataKey] ?? null;
        if (is_int($value) || is_float($value)) {
            $current = $stats[$statsKey] ?? null;
            $stats[$statsKey] = $current === null ? $value : max((float)$current, (float)$value);
        }
    }

    $stats['updated_at'] = $now;
    weather_realtime_atomic_write_json($path, $stats);
    return $stats;
}

function weather_realtime_normalize_mb(
    string $packet,
    string $stationId,
    string $source = 'mb-compatible',
    array $validation = []
): array {
    $fields = preg_split('/\s+/', trim($packet)) ?: [];
    $now = time();

    $windMs = weather_realtime_number($fields, 5);
    $gustMs = weather_realtime_number($fields, 6);
    $direction = weather_realtime_number($fields, 7);
    $pressure = weather_realtime_number($fields, 10);
    $pressure3hAgo = weather_realtime_number($fields, 18);

    $data = [
        'temperature_c' => weather_realtime_number($fields, 2),
        'temperature_min_c' => null,
        'temperature_max_c' => null,
        'humidity_pct' => weather_realtime_number($fields, 3),
        'dew_point_c' => weather_realtime_number($fields, 4),
        'heat_index_c' => weather_realtime_number($fields, 42),
        'wind_speed_kmh' => $windMs === null ? null : round($windMs * 3.6, 3),
        'wind_gust_kmh' => $gustMs === null ? null : round($gustMs * 3.6, 3),
        'wind_speed_max_kmh' => null,
        'wind_gust_max_kmh' => null,
        'wind_direction_deg' => $direction,
        'wind_direction_cardinal' => weather_realtime_cardinal($direction),
        'wind_chill_c' => weather_realtime_number($fields, 24),
        'pressure_hpa' => $pressure,
        'pressure_station_hpa' => null,
        'pressure_min_hpa' => null,
        'pressure_max_hpa' => null,
        'pressure_trend_3h_hpa' => (
            $pressure !== null && $pressure3hAgo !== null
                ? round($pressure - $pressure3hAgo, 2)
                : null
        ),
        'rain_rate_mmh' => weather_realtime_number($fields, 8),
        'rain_rate_max_mmh' => null,
        'rain_today_mm' => weather_realtime_number($fields, 9),
        'rain_last_hour_mm' => weather_realtime_number($fields, 47),
        'rain_last_24h_mm' => weather_realtime_number($fields, 44),
        'rain_total_mm' => weather_realtime_number($fields, 151),
        'indoor_temperature_c' => weather_realtime_number($fields, 22),
        'indoor_humidity_pct' => weather_realtime_number($fields, 23),
        'hardware_temperature_c' => weather_realtime_number($fields, 22),
        'uv_index' => weather_realtime_number($fields, 43),
        'solar_radiation_wm2' => null,
        'pm2_5_ugm3' => null,
        'lightning_distance_km' => null,
        'lightning_count' => null,
    ];

    $stats = weather_realtime_update_daily_stats($stationId, $data, $now);
    foreach ([
        'temperature_min_c',
        'temperature_max_c',
        'pressure_min_hpa',
        'pressure_max_hpa',
        'wind_speed_max_kmh',
        'wind_gust_max_kmh',
        'rain_rate_max_mmh',
    ] as $key) {
        $data[$key] = $stats[$key] ?? null;
    }

    return [
        'schema' => WEATHER_REALTIME_SCHEMA,
        'schema_version' => 1,
        'station_id' => $stationId,
        'source' => $source,
        'timestamp' => $now,
        'received_at' => gmdate('c', $now),
        'packet_time' => [
            'date' => weather_realtime_token($fields, 0),
            'time' => weather_realtime_token($fields, 1),
        ],
        'data' => $data,
        'meta' => [
            'field_count' => count($fields),
            'missing_fields' => isset($validation['missing']) ? (int)$validation['missing'] : null,
            'numeric_fields' => isset($validation['numeric']) ? (int)$validation['numeric'] : null,
            'station_type' => weather_realtime_token($fields, 25),
            'firmware' => weather_realtime_token($fields, 38),
            'controller_uptime_s' => weather_realtime_number($fields, 81),
        ],
    ];
}

function weather_realtime_store_mb(
    string $packet,
    string $stationId,
    string $source = 'mb-compatible',
    array $validation = []
): bool {
    $normalized = weather_realtime_normalize_mb($packet, $stationId, $source, $validation);
    return weather_realtime_atomic_write_json(
        weather_realtime_current_file($stationId),
        $normalized
    );
}

function weather_realtime_read_station(string $stationId): ?array
{
    return weather_realtime_read_json_file(weather_realtime_current_file($stationId));
}
