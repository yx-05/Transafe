import type { WsCallEventMessage, WsSessionMessage } from '../types/api';

export class SessionWebSocketClient {
  private ws: WebSocket | null = null;

  connect(
    baseUrl: string,
    sessionId: string,
    apiKey: string,
    onMessage: (msg: WsSessionMessage) => void,
    onError: (err: Event | string) => void,
    onClose: () => void
  ) {
    this.close();

    const wsUrl =
      baseUrl.replace(/^http/, 'ws') +
      `/ws/session/${encodeURIComponent(sessionId)}?api_key=${encodeURIComponent(apiKey)}`;
    
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

    this.ws.onclose = (event) => {
      if (event.code === 4001) {
        onError('WebSocket Auth Failed (Code 4001: Invalid API Key)');
      } else if (event.code === 4004) {
        onError('WebSocket Session Not Found (Code 4004)');
      }
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
    apiKey: string,
    onMessage: (msg: WsCallEventMessage) => void,
    onError: (err: Event | string) => void,
    onClose: () => void
  ) {
    this.close();

    const wsUrl =
      baseUrl.replace(/^http/, 'ws') +
      `/ws/call/${encodeURIComponent(callSessionId)}/events?api_key=${encodeURIComponent(apiKey)}`;
    
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

    this.ws.onclose = (event) => {
      if (event.code === 4001) {
        onError('Call Events WS Auth Failed (Code 4001: Invalid API Key)');
      }
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
