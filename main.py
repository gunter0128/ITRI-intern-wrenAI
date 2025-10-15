import os
import httpx
import json 
from pydantic import BaseModel
from typing import AsyncGenerator, Optional, Any, Dict

from fastapi import FastAPI, HTTPException, Path, Request, Header, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse

WREN_BASE_URL = "https://cloud.getwren.ai/api/v1"

app = FastAPI(title="Wren AI Core Proxy Server")

# 允許跨域請求 (CORS)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], 
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 定義請求體 (Request Body) 的結構
class WrenRequest(BaseModel):
    # 統一使用 project_id
    project_id: Optional[str] = None 
    text: Optional[str] = None
    additional_payload: Dict[str, Any] = {}

# --- 共用 HTTP 請求函數 ---

async def async_wren_call(
    method: str,
    full_url: str,
    json_data: Optional[Dict[str, Any]] = None,
    wren_api_key: str = None
) -> Dict[str, Any]:
    """執行非串流的 HTTP 請求。"""

    headers = {
        "Authorization": f"Bearer {wren_api_key}",
        "Content-Type": "application/json",
    }

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            print("-" * 50)
            print(f"DEBUG: Final Payload sent to Wren: {json_data}") 
            print(f"DEBUG: Request URL: {full_url}") 
            print("-" * 50)
            
            kwargs = {"headers": headers}
            if json_data is not None and method.upper() in ["POST", "PUT", "PATCH"]:
                kwargs["json"] = json_data
            
            response = await getattr(client, method.lower())(
                full_url, 
                **kwargs
            )
            
            response.raise_for_status()
            
            if response.status_code == 204 or response.content == b'':
                return {"message": "Operation successful, no content returned."}
            
            return response.json()
            
    except httpx.HTTPStatusError as e:
        error_content = e.response.text
        print(f"Wren API Error: {error_content}")

        try:
            error_data = e.response.json()
            error_detail = error_data.get('detail', error_content)
            
            if isinstance(error_detail, dict) or isinstance(error_detail, list):
                display_detail = json.dumps(error_detail)
            else:
                display_detail = str(error_detail)

        except:
            display_detail = error_content
            
        raise HTTPException(
            status_code=e.response.status_code, 
            detail=f"Wren API Request Failed (Method: {method}, Status: {e.response.status_code}): {display_detail}"
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"內部伺服器錯誤: {str(e)}")


# --- Route 1: Validate API Key (使用 /projects/{projectId} 驗證) ---

@app.get("/api/validate-key")
async def validate_api_key_and_project(
    wren_api_key: str = Header(..., alias="X-Wren-API-Key"),
    # 統一使用 project_id
    project_id: str = Query(..., description="Project ID to validate")
):
    """Verifies Key and Project ID by fetching project metadata."""
    wren_full_url = f"{WREN_BASE_URL}/projects/{project_id.strip()}"

    headers = {
        "Authorization": f"Bearer {wren_api_key.strip()}",
        "Content-Type": "application/json",
    }
    
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(wren_full_url, headers=headers)
            response.raise_for_status()
            return response.json()
            
    except httpx.HTTPStatusError as e:
        if e.response.status_code == 401:
            raise HTTPException(status_code=401, detail="API Key 驗證失敗或無效。")
        elif e.response.status_code == 403:
            raise HTTPException(status_code=403, detail="API Key 無權限訪問此 Project ID。")
        elif e.response.status_code == 404:
             raise HTTPException(status_code=404, detail="Project ID 不存在或 Key 無法存取。")
        else:
            raise HTTPException(status_code=e.response.status_code, detail=f"Wren API 請求失敗: {e.response.text}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"內部伺服器錯誤: {str(e)}")


# --- Route 2: Non-Streaming API Call (/generate_sql, /generate_vega_chart) ---

@app.post("/api/wren-call/{endpoint_path:path}")
async def handle_wren_query(
    request: Request,
    endpoint_path: str = Path(..., description="Target Wren AI API endpoint, e.g., generate_sql"),
    request_data: WrenRequest = None,
    wren_api_key: str = Header(..., alias="X-Wren-API-Key")
):
    """Proxies non-streaming requests to Wren AI Cloud API."""
    
    # 檢查 project_id 是否存在
    if not request_data.project_id or not request_data.project_id.strip():
        raise HTTPException(status_code=400, detail="project_id is required in the request body.")

    wren_full_url = f"{WREN_BASE_URL}/{endpoint_path}"

    try:
        # 將 project_id 轉換為整數
        project_id_int = int(request_data.project_id.strip())
    except ValueError:
        raise HTTPException(status_code=400, detail="project_id must be a valid integer.")

    # project_id 放回 JSON Body 並強制轉為 int
    wren_payload = {
        "question": request_data.text,
        "text": request_data.text,
        **request_data.additional_payload, 
        "projectId": project_id_int, 
    }

    return await async_wren_call(
        method=request.method,
        full_url=wren_full_url,
        json_data=wren_payload,
        wren_api_key=wren_api_key.strip()
    )

# --- Route 3: Streaming API Call (/stream/ask) ---

async def stream_wren_response(
    wren_full_url: str, 
    wren_payload: dict,
    wren_api_key: str
) -> AsyncGenerator[bytes, None]:
    """Handles SSE streaming response from Wren AI."""
    
    headers = {
        "Authorization": f"Bearer {wren_api_key}",
        "Content-Type": "application/json"
    }
    
    print("-" * 50)
    print(f"DEBUG: Final Streaming Payload sent to Wren: {wren_payload}")
    print(f"DEBUG: Request URL: {wren_full_url}") 
    print("-" * 50)

    async with httpx.AsyncClient(timeout=300.0) as client:
        try:
            async with client.stream("POST", wren_full_url, headers=headers, json=wren_payload) as response:
                
                # Critical Fix for ResponseNotRead: read error content on failure
                if response.status_code >= 400:
                    await response.aread()
                    response.raise_for_status()
                
                # Iterate over the response chunks
                async for chunk in response.aiter_bytes():
                    yield chunk
                    
        except httpx.HTTPStatusError as e:
            error_msg = f"Wren API Request Failed ({e.response.status_code}): {e.response.text}"
            print(f"Wren API Error: {error_msg}")
            
            # Yield error as an SSE event to the frontend
            try:
                error_data = json.loads(e.response.text)
                display_error = json.dumps({"error": error_data}, indent=2)
            except:
                display_error = f'{{"error": "{e.response.text}"}}'
                
            yield f"event: error\ndata: {display_error}\n\n".encode("utf-8")
        except Exception as e:
            error_msg = f"Internal Server Error: {str(e)}"
            print(error_msg)
            yield f"event: error\ndata: {error_msg}\n\n".encode("utf-8")


@app.post("/api/stream-call/{endpoint_path:path}")
async def handle_wren_streaming_query(
    endpoint_path: str = Path(..., description="Wren AI streaming API endpoint, e.g., stream/ask"),
    request_data: WrenRequest = None,
    wren_api_key: str = Header(..., alias="X-Wren-API-Key")
):
    """Proxies streaming (SSE) requests to Wren AI Cloud API."""
    
    # 檢查 project_id 是否存在
    if not request_data.project_id or not request_data.project_id.strip():
        raise HTTPException(status_code=400, detail="project_id is required in the request body.")
    
    wren_full_url = f"{WREN_BASE_URL}/{endpoint_path}"
    
    try:
        # 將 project_id 轉換為整數
        project_id_int = int(request_data.project_id.strip())
    except ValueError:
        raise HTTPException(status_code=400, detail="project_id must be a valid integer.")
    
    # project_id 放回 JSON Body 並強制轉為 int
    wren_payload = {
        "question": request_data.text,
        "text": request_data.text,
        **request_data.additional_payload, 
        "projectId": project_id_int, 
    }

    return StreamingResponse(
        stream_wren_response(wren_full_url, wren_payload, wren_api_key.strip()),
        media_type="text/event-stream"
    )