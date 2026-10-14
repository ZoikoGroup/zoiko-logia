import { act, renderHook, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
const auth = vi.hoisted(() => ({ current: { session: { user: { id: "overview-a" } } as {user:{id:string}} | null, profile: {tenant_id:"t1",role:"Admin"}, loading:false } }));
vi.mock("@/hooks/useAuth", () => ({ useAuth: () => auth.current }));
vi.mock("@/lib/api", () => ({ getAuthToken: () => "test-token", ApiError: class extends Error { constructor(public status:number,message:string){super(message);} } }));
import { ApiError } from "@/lib/api";
import { useLiveData } from "@/components/overview/useLiveData";
beforeEach(() => { auth.current = {session:{user:{id:"overview-a"}},profile:{tenant_id:"t1",role:"Admin"},loading:false}; });
describe("live overview data", () => {
  it("refetches when filters change without displaying the previous scope", async () => {
    const first = vi.fn().mockResolvedValue({count:12});
    let resolve: (value:{count:number}) => void = () => {};
    const second = vi.fn().mockImplementation(() => new Promise(r => { resolve=r; }));
    const {result,rerender} = renderHook(({key,fetcher})=>useLiveData(key,fetcher),{initialProps:{key:"filters:30",fetcher:first}});
    await waitFor(()=>expect(result.current.data).toEqual({count:12}));
    rerender({key:"filters:7",fetcher:second});
    expect(result.current.data).toBeNull();
    await act(async()=>{resolve({count:2});});
    await waitFor(()=>expect(result.current.data).toEqual({count:2}));
  });
  it("clears visible data on sign-out and account changes", async () => {
    const fetcher = vi.fn().mockResolvedValue({name:"A"});
    const {result,rerender} = renderHook(()=>useLiveData("account-isolation",fetcher));
    await waitFor(()=>expect(result.current.data).toEqual({name:"A"}));
    auth.current.session=null;
    rerender();
    expect(result.current.data).toBeNull();
    expect(result.current.signedOut).toBe(true);
    auth.current.session={user:{id:"overview-b"}};
    fetcher.mockImplementation(()=>new Promise(()=>{}));
    rerender();
    expect(result.current.data).toBeNull();
  });
  it("refreshes bypassing cache and removes records if access is revoked", async () => {
    const fetcher = vi.fn().mockResolvedValue({count:4});
    const {result} = renderHook(()=>useLiveData("revoked",fetcher));
    await waitFor(()=>expect(result.current.data).toEqual({count:4}));
    fetcher.mockRejectedValue(new ApiError(403,"Access revoked"));
    act(()=>result.current.reload());
    await waitFor(()=>expect(result.current.error).toBe("Access revoked"));
    expect(result.current.data).toBeNull();
    expect(fetcher.mock.calls.at(-1)?.[2]).toBe(true);
  });
});

it("does not restart an active refresh when focus triggers another reload", async () => {
  let resolve: (value: {count:number}) => void = () => {};
  const fetcher = vi.fn().mockImplementation(() => new Promise(r => { resolve=r; }));
  const {result} = renderHook(()=>useLiveData("in-flight-refresh",fetcher));
  await waitFor(()=>expect(fetcher).toHaveBeenCalledTimes(1));
  act(()=>{result.current.reload();result.current.reload();});
  expect(fetcher).toHaveBeenCalledTimes(1);
  await act(async()=>resolve({count:7}));
  await waitFor(()=>expect(result.current.data).toEqual({count:7}));
});
it("ends a stalled refresh and allows retry", async () => {
  const fetcher = vi.fn().mockImplementation(()=>new Promise(()=>{}));
  const {result} = renderHook(()=>useLiveData("stalled-refresh",fetcher,20));
  await waitFor(()=>expect(result.current.error).toContain("taking too long"));
  expect(result.current.loading).toBe(false);
  expect(fetcher.mock.calls[0][1].aborted).toBe(true);
  fetcher.mockResolvedValue({count:9});
  act(()=>result.current.reload());
  await waitFor(()=>expect(result.current.data).toEqual({count:9}));
});
