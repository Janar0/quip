export async function createVideoPipeline(source: MediaStream): Promise<{ stream: MediaStream; track: MediaStreamTrack; dispose: () => void }> {
  const sourceTrack = source.getVideoTracks()[0];
  if (!sourceTrack) throw new DOMException('Camera unavailable', 'NotFoundError');
  const settings = sourceTrack.getSettings();
  const camera = document.createElement('video');
  camera.muted = true;
  camera.playsInline = true;
  camera.autoplay = true;
  camera.srcObject = source;
  await camera.play();

  const canvas = document.createElement('canvas');
  canvas.width = settings.width || 640;
  canvas.height = settings.height || 480;
  const drawing = canvas.getContext('2d', { alpha: false });
  if (!drawing || typeof canvas.captureStream !== 'function') {
    camera.pause();
    camera.srcObject = null;
    throw new Error('camera_unavailable');
  }
  const sendStream = canvas.captureStream(2);
  const track = sendStream.getVideoTracks()[0];
  if (!track) throw new Error('camera_unavailable');
  let frameRequest = 0;
  let stopped = false;
  const pump = () => {
    if (stopped) return;
    try { drawing.drawImage(camera, 0, 0, canvas.width, canvas.height); } catch { /* wait for a drawable camera frame */ }
    frameRequest = requestAnimationFrame(pump);
  };
  frameRequest = requestAnimationFrame(pump);
  return {
    stream: sendStream,
    track,
    dispose: () => {
      stopped = true;
      if (frameRequest) cancelAnimationFrame(frameRequest);
      for (const frameTrack of sendStream.getTracks()) frameTrack.stop();
      camera.pause();
      camera.srcObject = null;
    },
  };
}

export function cameraErrorCode(error: unknown): string {
  return error instanceof DOMException && ['NotAllowedError', 'PermissionDeniedError'].includes(error.name)
    ? 'camera_permission_denied'
    : 'camera_unavailable';
}

/** Acquire only the selected devices, falling back to audio when camera permission fails. */
export async function requestLocalMedia(
  wantsCamera: boolean,
  getUserMedia: ((constraints: MediaStreamConstraints) => Promise<MediaStream>) | undefined,
  isCurrent: () => boolean,
  onCameraError: (code: string) => void,
): Promise<MediaStream | null> {
  const request = getUserMedia ?? navigator.mediaDevices?.getUserMedia?.bind(navigator.mediaDevices);
  if (!request) throw new Error('microphone_unavailable');
  let media: MediaStream;
  try {
    media = await request({
      audio: true,
      video: wantsCamera ? {
        facingMode: { ideal: 'user' }, frameRate: { ideal: 30, max: 30 },
        width: { ideal: 640 }, height: { ideal: 480 },
      } : false,
    });
  } catch (error) {
    if (!isCurrent()) return null;
    if (!wantsCamera) throw error;
    onCameraError(cameraErrorCode(error));
    media = await request({ audio: true, video: false });
  }
  if (!isCurrent()) {
    for (const track of media.getTracks()) track.stop();
    return null;
  }
  return media;
}
