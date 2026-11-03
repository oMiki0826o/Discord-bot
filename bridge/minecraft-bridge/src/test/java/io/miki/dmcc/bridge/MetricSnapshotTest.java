package io.miki.dmcc.bridge;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertThrows;

import org.junit.jupiter.api.Test;

class MetricSnapshotTest {
    @Test
    void capsTpsAtTwentyAndIncludesPopulation() {
        var metrics = MetricSnapshot.from(20.0, 3, 20);
        assertEquals(20.0, metrics.get("tps"));
        assertEquals(20.0, metrics.get("mspt"));
        assertEquals(3, metrics.get("online_players"));
        assertEquals(20, metrics.get("max_players"));
    }

    @Test
    void calculatesTpsForLaggingServer() {
        assertEquals(10.0, MetricSnapshot.from(100.0, 0, 20).get("tps"));
        assertEquals(20.0, MetricSnapshot.from(0.0, 0, 20).get("tps"));
    }

    @Test
    void rejectsCorruptTickTiming() {
        assertThrows(IllegalArgumentException.class, () -> MetricSnapshot.from(Double.NaN, 1, 20));
        assertThrows(IllegalArgumentException.class, () -> MetricSnapshot.from(Double.POSITIVE_INFINITY, 1, 20));
        assertThrows(IllegalArgumentException.class, () -> MetricSnapshot.from(-5, 1, 20));
        assertThrows(IllegalArgumentException.class, () -> MetricSnapshot.from(20, 21, 20));
    }
}
