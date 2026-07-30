import type { WsCallEventMessage, WsSessionMessage } from '../types/api';

export class SessionWebSocketClient {
  private ws: WebSocket | null = null;

  connect(
    baseUrl: string,
    sessionId: string,
    onMessage: (msg: WsSessionMessage) => void,
    onError: (err: Event) => void,
    onClose: () => void
  ) {
    this.close();

    const wsUrl = baseUrl.replace(/^http/, 'ws') + `/ws/session/${encodeURIComponent(sessionId)}`;
    this.ws = new WebSocket(wsUrl);

    this.ws.onmessage = (event) => {
      try {
        const data: WsSessionMessage = JSON.parse(event.data);
        onMessage(data);
      } catch (e) {
        console.error('Failed to parse WebSocket message', e);
      }
    };

    this.ws.onerror = (err) => {
      onError(err);
    };

    this.ws.onclose = () => {
      onClose();
    };
  }

  close() {
    if (this.ws) {
      this.ws.close();
      this.ws = null;
    }
  }
}

export class CallEventsWebSocketClient {
  private ws: WebSocket | null = null;

  connect(
    baseUrl: string,
    callSessionId: string,
    onMessage: (msg: WsCallEventMessage) => void,
    onError: (err: Event) => void,
    onClose: () => void
  ) {
    this.close();

    const wsUrl = baseUrl.replace(/^http/, 'ws') + `/ws/call/${encodeURIComponent(callSessionId)}/events`;
    this.ws = new WebSocket(wsUrl);

    this.ws.onmessage = (event) => {
      try {
        const data: WsCallEventMessage = JSON.parse(event.data);
        onMessage(data);
      } catch (e) {
        console.error('Failed to parse Call Event WS message', e);
      }
    };

    this.ws.onerror = (err) => {
      onError(err);
    };

    this.ws.onclose = () => {
      onClose();
    };
  }

  close() {
    if (this.ws) {
      this.ws.close();
      this.ws = null;
    }
  }
}
