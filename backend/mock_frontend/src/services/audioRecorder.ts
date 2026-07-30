export class CallAudioStreamer {
  private mediaRecorder: MediaRecorder | null = null;
  private mediaStream: MediaStream | null = null;
  private ws: WebSocket | null = null;
  private isRecording = false;

  public async startStreaming(
    baseUrl: string,
    callSessionId: string,
    onStatusChange: (status: string) => void,
    onError: (errorMsg: string) => void
  ): Promise<void> {
    try {
      this.stopStreaming();

      // Request browser microphone permission
      this.mediaStream = await navigator.mediaDevices.getUserMedia({
        audio: {
          channelCount: 1,
          sampleRate: 16000,
          echoCancellation: true,
          noiseSuppression: true,
        },
      });

      // Connect binary WebSocket
      const wsUrl = baseUrl.replace(/^http/, 'ws') + `/ws/call/${encodeURIComponent(callSessionId)}/audio`;
      this.ws = new WebSocket(wsUrl);
      this.ws.binaryType = 'arraybuffer';

      this.ws.onopen = () => {
        onStatusChange('Connected & Recording Live Audio...');
        this.startMediaRecorder(onError);
      };

      this.ws.onerror = (err) => {
        console.error('Audio WS Error:', err);
        onError('Audio WebSocket Connection Error');
      };

      this.ws.onclose = () => {
        onStatusChange('Audio WebSocket Closed');
      };
    } catch (err: any) {
      console.error('Microphone error:', err);
      onError(err.message || 'Microphone Access Denied');
    }
  }

  private startMediaRecorder(onError: (errorMsg: string) => void) {
    if (!this.mediaStream || !this.ws) return;

    try {
      const mimeType = MediaRecorder.isTypeSupported('audio/webm;codecs=opus')
        ? 'audio/webm;codecs=opus'
        : MediaRecorder.isTypeSupported('audio/mp4')
        ? 'audio/mp4'
        : 'audio/webm';

      this.mediaRecorder = new MediaRecorder(this.mediaStream, { mimeType });

      this.mediaRecorder.ondataavailable = async (event) => {
        if (event.data.size > 0 && this.ws && this.ws.readyState === WebSocket.OPEN) {
          const buffer = await event.data.arrayBuffer();
          this.ws.send(buffer);
        }
      };

      // Stream audio chunk every 1 second
      this.mediaRecorder.start(1000);
      this.isRecording = true;
    } catch (e: any) {
      onError('MediaRecorder init failed: ' + e.message);
    }
  }

  public stopStreaming(): void {
    if (this.mediaRecorder && this.mediaRecorder.state !== 'inactive') {
      this.mediaRecorder.stop();
      this.mediaRecorder = null;
    }

    if (this.mediaStream) {
      this.mediaStream.getTracks().forEach((track) => track.stop());
      this.mediaStream = null;
    }

    if (this.ws) {
      this.ws.close();
      this.ws = null;
    }

    this.isRecording = false;
  }

  public get active(): boolean {
    return this.isRecording;
  }
}
