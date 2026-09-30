import { fireEvent, render, screen, waitFor } from '@testing-library/svelte';
import { beforeEach, expect, it, vi } from 'vitest';

import ModelsPage from '../routes/(app)/admin/models/+page.svelte';

const toastMocks = vi.hoisted(() => ({ success: vi.fn(), error: vi.fn() }));
const fetchMock = vi.hoisted(() => vi.fn());
vi.mock('svelte-sonner', () => ({ toast: toastMocks }));

const oldModel = 'z-ai/glm-5.2';
const newModel = 'z-ai/glm-6';
const settings = {
  openrouter_api_key_set: true,
  model_whitelist: [oldModel],
  model_aliases: {},
  default_model: oldModel,
  search_model: '',
  research_model: '',
  title_model: newModel,
};
const report = {
  updated: [{
    old_id: oldModel,
    new_id: newModel,
    references: ['model_whitelist', 'default_model'],
    price_change: { prompt: { before: '0.000001', after: '0.000003', percent_change: '200' } },
  }],
  skipped: [{ model_id: 'z-ai/glm-5.1', reason: 'ambiguous' }],
  mapper_model: newModel,
  models: [{ id: newModel, name: newModel }],
  settings: { ...settings, model_whitelist: [newModel], default_model: newModel },
};
let updateError: string | null = null;

beforeEach(() => {
  vi.clearAllMocks();
  Object.defineProperty(Element.prototype, 'animate', {
    configurable: true,
    value: vi.fn(() => ({ cancel: vi.fn() })),
  });
  updateError = null;
  fetchMock.mockReset().mockImplementation(async (input: RequestInfo | URL) => {
    const path = String(input);
    if (path === '/api/admin/settings') return Response.json(settings);
    if (path === '/api/admin/models') return Response.json({ models: [{ id: newModel, name: newModel }] });
    if (path === '/api/admin/models/update') {
      return updateError
        ? Response.json({ detail: updateError }, { status: 502 })
        : Response.json(report);
    }
    return Response.json({}, { status: 404 });
  });
  vi.stubGlobal('fetch', fetchMock);
});

it('runs the updater from the button and displays saved changes, skipped models, and price deltas', async () => {
  render(ModelsPage);

  const button = await screen.findByRole('button', { name: 'admin.updateModels' });
  await waitFor(() => expect(button.hasAttribute('disabled')).toBe(false));
  await fireEvent.click(button);

  await waitFor(() => expect(fetchMock.mock.calls.some(([path]) => path === '/api/admin/models/update')).toBe(true));
  const updateCall = fetchMock.mock.calls.find(([path]) => path === '/api/admin/models/update');
  expect(updateCall?.[1]).toMatchObject({ method: 'POST' });
  expect(await screen.findByText(oldModel)).toBeTruthy();
  expect(screen.getAllByText(newModel).length).toBeGreaterThan(0);
  expect(screen.getByText(/0\.000001/)).toBeTruthy();
  expect(screen.getByText(/admin\.modelUpdateReferences/).getAttribute('style')).toContain('--quip-text-muted');
  expect(screen.getByText(/admin\.modelUpdateReason\.ambiguous/).getAttribute('style')).toContain('--quip-text-muted');
  expect(screen.getByText(/admin\.modelUpdateReason\.ambiguous/)).toBeTruthy();
  expect(toastMocks.success).toHaveBeenCalled();
});

it('shows the updater error returned by the API without a success report', async () => {
  updateError = 'Catalog unavailable';
  render(ModelsPage);

  const button = await screen.findByRole('button', { name: 'admin.updateModels' });
  await waitFor(() => expect(button.hasAttribute('disabled')).toBe(false));
  await fireEvent.click(button);

  await waitFor(() => expect(toastMocks.error).toHaveBeenCalledWith('Catalog unavailable'));
  expect(screen.queryByText(oldModel)).toBeNull();
});

it('disables model-setting saves while the updater is in flight', async () => {
  let finishUpdate!: (response: Response) => void;
  const pendingUpdate = new Promise<Response>((resolve) => {
    finishUpdate = resolve;
  });
  fetchMock.mockImplementation(async (input: RequestInfo | URL) => {
    const path = String(input);
    if (path === '/api/admin/settings') return Response.json(settings);
    if (path === '/api/admin/models') return Response.json({ models: [{ id: newModel, name: newModel }] });
    if (path === '/api/admin/models/update') return pendingUpdate;
    return Response.json({}, { status: 404 });
  });

  render(ModelsPage);
  const updateButton = await screen.findByRole('button', { name: 'admin.updateModels' });
  await waitFor(() => expect(updateButton.hasAttribute('disabled')).toBe(false));
  await fireEvent.click(updateButton);

  await waitFor(() => expect(updateButton.hasAttribute('disabled')).toBe(true));
  const saveButtons = screen.getAllByRole('button', { name: 'common.save' });
  expect(saveButtons.length).toBeGreaterThan(0);
  expect(saveButtons.every((button) => button.hasAttribute('disabled'))).toBe(true);
  expect(fetchMock.mock.calls.filter(([path]) => path === '/api/admin/models/update')).toHaveLength(1);

  finishUpdate(Response.json(report));
  await waitFor(() => expect(updateButton.hasAttribute('disabled')).toBe(false));
});
