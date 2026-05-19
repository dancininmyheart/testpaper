import axios, { AxiosError, InternalAxiosRequestConfig } from "axios";
import type { ApiResponse, ApiErrorResponse } from "./types";

const apiClient = axios.create({
  baseURL: "/api/v1",
  timeout: 30000,
  headers: { "Content-Type": "application/json" },
});

let getToken: () => string | null = () => null;
let onUnauthorized: () => void = () => {};

export function configureAuth(tokenGetter: () => string | null, logoutHandler: () => void) {
  getToken = tokenGetter;
  onUnauthorized = logoutHandler;
}

apiClient.interceptors.request.use((config: InternalAxiosRequestConfig) => {
  const token = getToken();
  if (token) {
    config.headers.Authorization = `Bearer ${token}`;
  }
  return config;
});

apiClient.interceptors.response.use(
  (response) => response,
  (error: AxiosError<ApiErrorResponse>) => {
    if (error.response?.status === 401) {
      onUnauthorized();
    }
    const errData = error.response?.data;
    if (errData && !errData.ok) {
      const apiError = new Error(errData.error?.message || "未知错误");
      (apiError as any).code = errData.error?.code;
      return Promise.reject(apiError);
    }
    if (error.code === "ECONNABORTED") {
      const apiError = new Error("请求超时，MinerU 正在处理中，请稍后重试或联系管理员检查 MinerU 服务状态");
      (apiError as any).code = "TIMEOUT";
      return Promise.reject(apiError);
    }
    if (!error.response) {
      const apiError = new Error("网络连接失败，请检查服务器是否在线");
      (apiError as any).code = "NETWORK_ERROR";
      return Promise.reject(apiError);
    }
    return Promise.reject(error);
  },
);

export async function apiGet<T>(url: string, params?: Record<string, any>): Promise<T> {
  const resp = await apiClient.get<ApiResponse<T>>(url, { params });
  return resp.data.data;
}

export async function apiPost<T>(url: string, body?: any, opts?: { timeout?: number }): Promise<T> {
  const resp = await apiClient.post<ApiResponse<T>>(url, body, opts);
  return resp.data.data;
}

export async function apiPatch<T>(url: string, body?: any): Promise<T> {
  const resp = await apiClient.patch<ApiResponse<T>>(url, body);
  return resp.data.data;
}

export async function apiPostForm<T>(url: string, formData: FormData): Promise<T> {
  const resp = await apiClient.post<ApiResponse<T>>(url, formData, {
    headers: { "Content-Type": "multipart/form-data" },
  });
  return resp.data.data;
}

export async function apiDelete<T>(url: string): Promise<T> {
  const resp = await apiClient.delete<ApiResponse<T>>(url);
  return resp.data.data;
}

export async function apiGetBlob(url: string): Promise<Blob> {
  const resp = await apiClient.get(url, { responseType: "blob" });
  return resp.data;
}

export { apiClient };
