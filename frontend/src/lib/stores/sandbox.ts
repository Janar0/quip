export interface ToolExecution {
  id: string;
  name: string;
  arguments?: string;
  status: 'running' | 'completed' | 'error';
  result?: Record<string, unknown>;
}
