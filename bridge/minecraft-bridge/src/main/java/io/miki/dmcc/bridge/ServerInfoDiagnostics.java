package io.miki.dmcc.bridge;

import java.util.LinkedHashMap;
import java.util.Map;

/** Builds the versioned DMCC sender diagnostics included in server-info responses. */
final class ServerInfoDiagnostics {
    private ServerInfoDiagnostics() { }

    static Map<String, Object> from(BridgeRuntime runtime) {
        Throwable failure = runtime.lastSenderFailure();
        Map<String, Object> values = new LinkedHashMap<>();
        values.put("required_queue_depth", runtime.requiredQueueDepth());
        values.put("required_queue_capacity", runtime.requiredQueueCapacity());
        values.put("event_queue_depth", runtime.eventQueueDepth());
        values.put("event_queue_capacity", runtime.eventQueueCapacity());
        values.put("dropped_events", runtime.droppedEvents());
        values.put("last_sender_failure", failure == null ? "" : failure.getClass().getSimpleName());
        return Map.copyOf(values);
    }
}
