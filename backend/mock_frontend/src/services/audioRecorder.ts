export class CallAudioStreamer {
  private mediaRecorder: MediaRecorder | null = null;
  private mediaStream: MediaStream | null = null;
  private ws: WebSocket | null = null;
  private isRecording = false;

  // MediaSource API audio player for streaming WebM opus chunks
  private audioElement: HTMLAudioElement | null = null;
  private mediaSource: MediaSource | null = null;
  private sourceBuffer: SourceBuffer | null = null;
  private audioQueue: Uint8Array[] = [];
  private isAppending = false;

  public async startStreaming(
    baseUrl: string,
    callSessionId: string,
    apiKey: string,
    role: 'SCAMMER' | 'CUSTOMER' = 'CUSTOMER',
    onStatusChange: (status: string) => void,
    onError: (errorMsg: string) => void
  ): Promise<void> {
    try {
      this.stopStreaming();

      if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
        throw new Error(
          'Microphone API disabled on plain HTTP network IP. Mobile browsers require HTTPS or localhost for microphone access.'
        );
      }

      // 1. Initialize HTML5 MediaSource audio player for live peer speaker playback
      this.initMediaSourcePlayer();

      // 2. Request browser microphone permission
      this.mediaStream = await navigator.mediaDevices.getUserMedia({
        audio: {
          channelCount: 1,
          sampleRate: 16000,
          echoCancellation: true,
          noiseSuppression: true,
        },
      });

      // 3. Connect binary WebSocket with api_key & role query params
      const wsUrl =
        baseUrl.replace(/^http/, 'ws') +
        `/ws/call/${encodeURIComponent(callSessionId)}/audio?api_key=${encodeURIComponent(apiKey)}&role=${encodeURIComponent(role)}`;

      this.ws = new WebSocket(wsUrl);
      this.ws.binaryType = 'arraybuffer';

      this.ws.onopen = () => {
        onStatusChange(`Connected (${role}) & Streaming Audio...`);
        this.startMediaRecorder(onError);
      };

      // 4. Play incoming peer audio frames
      this.ws.onmessage = (event) => {
        if (event.data instanceof ArrayBuffer) {
          this.enqueuePeerAudioChunk(event.data);
        }
      };

      this.ws.onerror = (err) => {
        console.error('Audio WS Error:', err);
        onError('Audio WebSocket Connection Error (Check API Key)');
      };

      this.ws.onclose = (event) => {
        if (event.code === 4001) {
          onError('Audio WS Auth Failed (Code 4001: Invalid API Key)');
        }
        onStatusChange('Audio WebSocket Closed');
      };
    } catch (err: any) {
      console.error('Microphone error:', err);
      onError(err.message || 'Microphone Access Denied');
    }
  }

  private initMediaSourcePlayer() {
    try {
      if ('MediaSource' in window) {
        this.mediaSource = new MediaSource();
        this.audioElement = new Audio();
        this.audioElement.src = URL.createObjectURL(this.mediaSource);

        this.mediaSource.addEventListener('sourceopen', () => {
          const mimeType = 'audio/webm;codecs=opus';
          if (MediaSource.isTypeSupported(mimeType)) {
            try {
              this.sourceBuffer = this.mediaSource!.addSourceBuffer(mimeType);
              this.sourceBuffer.mode = 'sequence';
              this.sourceBuffer.addEventListener('updateend', () => {
                this.isAppending = false;
                this.processAudioQueue();
              });
            } catch (e) {
              console.warn('SourceBuffer init warning:', e);
            }
          }
        });

        this.audioElement.play().catch(() => {});
      }
    } catch (e) {
      console.error('MediaSource player init failed:', e);
    }
  }

  private enqueuePeerAudioChunk(arrayBuffer: ArrayBuffer) {
    const chunk = new Uint8Array(arrayBuffer);
    this.audioQueue.push(chunk);
    this.processAudioQueue();
  }

  private processAudioQueue() {
    if (this.sourceBuffer && !this.isAppending && this.audioQueue.length > 0) {
      if (!this.sourceBuffer.updating) {
        try {
          const chunk = this.audioQueue.shift();
          if (chunk) {
            this.isAppending = true;
            this.sourceBuffer.appendBuffer(chunk);
          }
        } catch (e) {
          this.isAppending = false;
        }
      }
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

      // Stream audio chunk every 500ms
      this.mediaRecorder.start(500);
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

    if (this.audioElement) {
      this.audioElement.pause();
      this.audioElement = null;
    }

    this.mediaSource = null;
    this.sourceBuffer = null;
    this.audioQueue = [];
    this.isAppending = false;
    this.isRecording = false;
  }

  public get active(): boolean {
    return this.isRecording;
  }
}

/**
 * Play a TranSafe AUTO_TALK agent speech MP3 via a plain HTML5 <audio> element.
 *
 * The agent's voice is delivered as MP3 (edge-tts) over a REST endpoint — NOT
 * through the WebM/Opus peer-relay player — so this uses a simple blob URL
 * instead of the MediaSource pipeline.
 */

// Serialized agent-speech playback: STT delivers sentence fragments and each
// one triggers a new `talking` event, so without pacing the agent's audio
// overlaps with itself. We play one utterance at a time and let the newest
// utterance replace any pending one (newest-wins). `force` (used for the
// hangup farewell) interrupts whatever is currently playing.
let activeAudio: HTMLAudioElement | null = null;
let activePlaybackId: string | null = null;
let activeResolve: (() => void) | null = null;
let pendingPlayback: {
  baseUrl: string;
  callSessionId: string;
  ttsId: string;
  apiKey: string;
  force: boolean;
} | null = null;

function finishActivePlayback() {
  if (activeResolve) activeResolve();
  activeResolve = null;
  activePlaybackId = null;
  activeAudio = null;
  const next = pendingPlayback;
  pendingPlayback = null;
  if (next) {
    playAgentSpeech(next.baseUrl, next.callSessionId, next.ttsId, next.apiKey, next.force);
  }
}

export function playAgentSpeech(
  baseUrl: string,
  callSessionId: string,
  ttsId: string,
  apiKey: string,
  force = false
): Promise<void> {
  // Hangup / final farewell interrupts whatever is currently playing so the
  // customer always hears the agent's last line before the call ends.
  if (force && activePlaybackId !== null) {
    const wasAudio = activeAudio;
    const wasResolve = activeResolve;
    activeResolve = null;
    if (wasAudio) {
      try {
        wasAudio.pause();
      } catch {
        /* noop */
      }
    }
    if (wasResolve) wasResolve();
    activePlaybackId = null;
    activeAudio = null;
  }

  if (activePlaybackId !== null) {
    // Newest-wins: remember the latest utterance and play it once the current
    // one finishes, so the agent never talks over itself.
    pendingPlayback = { baseUrl, callSessionId, ttsId, apiKey, force };
    return Promise.resolve();
  }

  activePlaybackId = ttsId;
  const url =
    `${baseUrl}/api/v1/call/${encodeURIComponent(callSessionId)}/tts/${encodeURIComponent(ttsId)}`;
  return new Promise((resolve) => {
    activeResolve = resolve;
    fetch(url, { headers: { 'X-API-Key': apiKey } })
      .then((res) => {
        if (!res.ok) throw new Error(`TTS fetch failed: ${res.status}`);
        return res.blob();
      })
      .then((blob) => {
        const audio = new Audio(URL.createObjectURL(blob));
        activeAudio = audio;
        const done = () => {
          if (activeResolve === resolve) finishActivePlayback();
          else if (activeAudio === audio) activeAudio = null;
        };
        audio.onended = done;
        audio.onerror = () => {
          console.error(`[TTS] playback error for ${ttsId}`);
          done();
        };
        audio.play().catch((err) => {
          // Autoplay policies can reject play() — surface it instead of hiding it.
          console.error(`[TTS] play() blocked for ${ttsId}:`, err?.message || err);
          done();
        });
      })
      .catch((err) => {
        console.error(`[TTS] failed to load ${ttsId}:`, err?.message || err);
        if (activeResolve === resolve) finishActivePlayback();
      });
  });
}
