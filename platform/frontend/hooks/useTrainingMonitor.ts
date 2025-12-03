/**
 * React Hook for Real-time Training Monitoring
 *
 * Connects to WebSocket for live training updates
 */

import { useEffect, useRef, useState, useCallback } from 'react';

export interface TrainingStatus {
  job_id: number;
  status: 'pending' | 'running' | 'completed' | 'failed' | 'cancelled';
  execution_id?: string;
  started_at?: string;
  completed_at?: string;
  progress?: number;
  current_epoch?: number;
  total_epochs?: number;
}

export interface TrainingMetrics {
  job_id: number;
  epoch: number;
  total_epochs?: number;
  loss: number;
  accuracy?: number;
  val_loss?: number;
  val_accuracy?: number;
  learning_rate?: number;
  timestamp: string;
}

export interface TrainingLog {
  job_id: number;
  message: string;
  level: 'INFO' | 'WARNING' | 'ERROR';
  timestamp: string;
}

export type TrainingMessage =
  | { type: 'connected'; message: string; timestamp: string }
  | { type: 'training_status_change'; job_id: number; old_status: string; new_status: string; timestamp: string }
  | { type: 'training_metrics'; job_id: number; metrics: TrainingMetrics }
  | { type: 'training_log'; job_id: number; level: string; event_type: string; message: string; timestamp: string }
  | { type: 'training_complete'; job_id: number; timestamp: string }
  | { type: 'training_error'; job_id: number; error: string; timestamp: string }
  | { type: 'export_status_change'; job_id: number; export_job_id: number; old_status: string; new_status: string; timestamp: string }
  | { type: 'export_complete'; job_id: number; export_job_id: number; timestamp: string }
  | { type: 'export_error'; job_id: number; export_job_id: number; error: string; timestamp: string }
  | { type: 'pong' };

export interface UseTrainingMonitorOptions {
  jobId?: number;
  sessionId?: number;
  autoConnect?: boolean;
  reconnectInterval?: number;
  maxReconnectAttempts?: number;
  onMessage?: (message: TrainingMessage) => void;
  onStatusChange?: (jobId: number, oldStatus: string, newStatus: string) => void;
  onMetrics?: (jobId: number, metrics: TrainingMetrics) => void;
  onLog?: (jobId: number, log: TrainingLog) => void;
  onExportStatusChange?: (jobId: number, exportJobId: number, oldStatus: string, newStatus: string) => void;
  onConnect?: () => void;
  onDisconnect?: () => void;
  onError?: (error: Event) => void;
}

export function useTrainingMonitor(options: UseTrainingMonitorOptions = {}) {
  const {
    jobId,
    sessionId,
    autoConnect = true,
    reconnectInterval = 3000,
    maxReconnectAttempts = 10,
    onMessage,
    onStatusChange,
    onMetrics,
    onLog,
    onExportStatusChange,
    onConnect,
    onDisconnect,
    onError,
  } = options;

  const [isConnected, setIsConnected] = useState(false);
  const [reconnectAttempts, setReconnectAttempts] = useState(0);
  const [lastMessage, setLastMessage] = useState<TrainingMessage | null>(null);

  const wsRef = useRef<WebSocket | null>(null);
  const reconnectTimeoutRef = useRef<NodeJS.Timeout | null>(null);
  const pingIntervalRef = useRef<NodeJS.Timeout | null>(null);

  const connect = useCallback(() => {
    // Prevent duplicate connections (including CONNECTING and CLOSING states)
    if (wsRef.current) {
      const state = wsRef.current.readyState;
      if (state === WebSocket.OPEN || state === WebSocket.CONNECTING) {
        console.log('[TrainingMonitor] Already connected or connecting');
        return;
      }
    }

    // Build WebSocket URL
    const wsProtocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    // Extract just the host:port from API URL (remove protocol and /api/v1 path)
    const apiUrl = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000/api/v1';
    const wsHost = apiUrl.replace(/^https?:\/\//, '').replace(/\/api\/v1$/, '') || 'localhost:8000';
    let wsUrl = `${wsProtocol}//${wsHost}/api/v1/ws/training`;

    // Add query parameters
    const params = new URLSearchParams();
    if (jobId) params.append('job_id', jobId.toString());
    if (sessionId) params.append('session_id', sessionId.toString());
    if (params.toString()) {
      wsUrl += `?${params.toString()}`;
    }

    console.log('[TrainingMonitor] Connecting to', wsUrl);

    try {
      const ws = new WebSocket(wsUrl);

      ws.onopen = () => {
        console.log('[TrainingMonitor] Connected');
        setIsConnected(true);
        setReconnectAttempts(0);
        onConnect?.();

        // Start ping interval
        pingIntervalRef.current = setInterval(() => {
          if (ws.readyState === WebSocket.OPEN) {
            ws.send(JSON.stringify({ type: 'ping' }));
          }
        }, 30000); // Ping every 30 seconds
      };

      ws.onmessage = (event) => {
        try {
          const message: TrainingMessage = JSON.parse(event.data);
          setLastMessage(message);
          onMessage?.(message);

          // Handle specific message types
          if (message.type === 'training_status_change') {
            onStatusChange?.(message.job_id, message.old_status, message.new_status);
          } else if (message.type === 'training_metrics' || message.type === 'training_progress') {
            // Handle both training_metrics and training_progress (real-time updates from callbacks)
            onMetrics?.(message.job_id, message.metrics);
          } else if (message.type === 'training_log') {
            // Convert backend message format to TrainingLog format
            const log: TrainingLog = {
              job_id: message.job_id,
              message: message.message,
              level: message.level,
              timestamp: message.timestamp,
            };
            onLog?.(message.job_id, log);
          } else if (message.type === 'export_status_change' || message.type === 'export_complete' || message.type === 'export_error') {
            const oldStatus = message.type === 'export_status_change' ? message.old_status : '';
            const newStatus = message.type === 'export_status_change' ? message.new_status :
                             message.type === 'export_complete' ? 'completed' : 'failed';
            onExportStatusChange?.(message.job_id, message.export_job_id, oldStatus, newStatus);
          }
        } catch (error) {
          console.error('[TrainingMonitor] Error parsing message:', error);
        }
      };

      ws.onerror = (event) => {
        console.error('[TrainingMonitor] WebSocket error:', event);
        onError?.(event);
      };

      ws.onclose = () => {
        console.log('[TrainingMonitor] Disconnected');
        setIsConnected(false);
        onDisconnect?.();

        // Clear ping interval
        if (pingIntervalRef.current) {
          clearInterval(pingIntervalRef.current);
          pingIntervalRef.current = null;
        }

        // Attempt reconnection
        if (reconnectAttempts < maxReconnectAttempts) {
          console.log(`[TrainingMonitor] Reconnecting in ${reconnectInterval}ms (attempt ${reconnectAttempts + 1}/${maxReconnectAttempts})`);
          reconnectTimeoutRef.current = setTimeout(() => {
            setReconnectAttempts((prev) => prev + 1);
            connect();
          }, reconnectInterval);
        } else {
          console.error('[TrainingMonitor] Max reconnection attempts reached');
        }
      };

      wsRef.current = ws;
    } catch (error) {
      console.error('[TrainingMonitor] Failed to create WebSocket:', error);
    }
  }, [jobId, sessionId, reconnectAttempts, reconnectInterval, maxReconnectAttempts, onConnect, onDisconnect, onError, onMessage, onStatusChange, onMetrics, onLog, onExportStatusChange]);

  const disconnect = useCallback(() => {
    if (pingIntervalRef.current) {
      clearInterval(pingIntervalRef.current);
      pingIntervalRef.current = null;
    }

    if (reconnectTimeoutRef.current) {
      clearTimeout(reconnectTimeoutRef.current);
      reconnectTimeoutRef.current = null;
    }

    if (wsRef.current) {
      wsRef.current.close();
      wsRef.current = null;
    }

    setIsConnected(false);
  }, []);

  const send = useCallback((message: any) => {
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify(message));
    } else {
      console.warn('[TrainingMonitor] Cannot send message: not connected');
    }
  }, []);

  const subscribe = useCallback((jobId: number) => {
    send({ type: 'subscribe', job_id: jobId });
  }, [send]);

  const unsubscribe = useCallback((jobId: number) => {
    send({ type: 'unsubscribe', job_id: jobId });
  }, [send]);

  // Auto-connect on mount
  useEffect(() => {
    if (autoConnect) {
      connect();
    }

    return () => {
      disconnect();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [autoConnect]); // Only depend on autoConnect to prevent reconnection loops

  return {
    isConnected,
    lastMessage,
    reconnectAttempts,
    connect,
    disconnect,
    send,
    subscribe,
    unsubscribe,
  };
}
