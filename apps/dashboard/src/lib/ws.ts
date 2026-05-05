/**
 * Multiplexed WebSocket client for KrakenOps live topics.
 *
 * One socket per browser session. Components subscribe to topics via the
 * useLatestMessage / useTopicListener hooks; the underlying WSClient
 * fan-outs each incoming frame to all listeners of the matching topic.
 *
 * Auto-reconnects with exponential backoff. SSR-safe: the client is only
 * instantiated lazily inside browser code paths.
 */

import { API_BASE } from "@/lib/api";
import { useEffect, useRef, useState } from "react";

export type Topic = "metrics" | "traces" | "kanban" | "processes" | "events";

export interface TopicMessage<T = unknown> {
  topic: Topic;
  ts: number; // unix nanoseconds
  data: T;
}

export const WS_URL: string = `${API_BASE.replace(/^http/, "ws")}/v1/ws`;

const ALL_TOPICS: Topic[] = ["metrics", "traces", "kanban", "processes", "events"];

type Listener = (msg: TopicMessage) => void;

class WSClient {
  private ws: WebSocket | null = null;
  private listeners: Map<Topic, Set<Listener>> = new Map();
  private connectAttempts = 0;
  private closedDeliberately = false;

  subscribe(topic: Topic, cb: Listener): () => void {
    let set = this.listeners.get(topic);
    if (!set) {
      set = new Set();
      this.listeners.set(topic, set);
    }
    set.add(cb);
    this.ensureConnected();
    return () => {
      set?.delete(cb);
    };
  }

  private ensureConnected(): void {
    if (
      this.ws &&
      (this.ws.readyState === WebSocket.OPEN || this.ws.readyState === WebSocket.CONNECTING)
    ) {
      return;
    }
    this.connect();
  }

  private connect(): void {
    const url = `${WS_URL}?topics=${ALL_TOPICS.join(",")}`;
    this.closedDeliberately = false;
    this.ws = new WebSocket(url);

    this.ws.onopen = () => {
      this.connectAttempts = 0;
    };

    this.ws.onmessage = (e) => {
      let msg: TopicMessage;
      try {
        msg = JSON.parse(e.data) as TopicMessage;
      } catch {
        return;
      }
      const set = this.listeners.get(msg.topic);
      if (!set) return;
      for (const cb of set) {
        try {
          cb(msg);
        } catch (err) {
          console.error("ws listener error", err);
        }
      }
    };

    this.ws.onerror = () => {
      this.ws?.close();
    };

    this.ws.onclose = () => {
      this.ws = null;
      if (this.closedDeliberately) return;
      const delay = Math.min(500 * 2 ** this.connectAttempts, 15_000);
      this.connectAttempts += 1;
      setTimeout(() => this.ensureConnected(), delay);
    };
  }

  close(): void {
    this.closedDeliberately = true;
    this.ws?.close();
    this.ws = null;
  }
}

let _client: WSClient | null = null;

export function getWSClient(): WSClient {
  if (typeof window === "undefined") {
    throw new Error("getWSClient is browser-only");
  }
  if (!_client) {
    _client = new WSClient();
  }
  return _client;
}

// --- React hooks ---------------------------------------------------------

/** Returns the latest payload received on `topic`, or null until one arrives. */
export function useLatestMessage<T>(topic: Topic): { data: T | null; ts: number | null } {
  const [state, setState] = useState<{ data: T | null; ts: number | null }>({
    data: null,
    ts: null,
  });
  useEffect(() => {
    return getWSClient().subscribe(topic, (msg) => {
      setState({ data: msg.data as T, ts: msg.ts });
    });
  }, [topic]);
  return state;
}

/** Side-effect subscription: fire `callback` for every message on `topic`. */
export function useTopicListener<T>(topic: Topic, callback: (msg: TopicMessage<T>) => void): void {
  const cbRef = useRef(callback);
  useEffect(() => {
    cbRef.current = callback;
  });
  useEffect(() => {
    return getWSClient().subscribe(topic, (msg) => {
      cbRef.current(msg as TopicMessage<T>);
    });
  }, [topic]);
}
