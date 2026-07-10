package ae.lf.training.judge.data.api

import retrofit2.Response
import retrofit2.http.Body
import retrofit2.http.GET
import retrofit2.http.POST
import retrofit2.http.Path
import retrofit2.http.Query

interface MobileApiService {
    @GET("api/mobile/v1/ping")
    suspend fun ping(): Response<Map<String, Any?>>

    @POST("api/mobile/v1/auth/login")
    suspend fun login(@Body body: LoginRequest): Response<ApiResponse<UserDto>>

    @POST("api/mobile/v1/auth/logout")
    suspend fun logout(): Response<ApiResponse<Unit>>

    @GET("api/mobile/v1/session")
    suspend fun session(): Response<ApiResponse<UserDto>>

    @GET("api/mobile/v1/judge/hub")
    suspend fun judgeHub(): Response<ApiResponse<Unit>>

    @GET("api/mobile/v1/judge/evaluation-lists")
    suspend fun evalListsHome(): Response<ApiResponse<Unit>>

    @GET("api/mobile/v1/judge/evaluation-lists/{unitKey}")
    suspend fun evalListsUnit(
        @Path("unitKey") unitKey: String,
        @Query("phase") phase: String?,
    ): Response<ApiResponse<Unit>>

    @GET("api/mobile/v1/judge/evaluation-lists/{unitKey}/{itemId}")
    suspend fun evalDetail(
        @Path("unitKey") unitKey: String,
        @Path("itemId") itemId: Int,
    ): Response<EvalDetailResponse>

    @POST("api/mobile/v1/judge/evaluation-lists/{unitKey}/{itemId}/save")
    suspend fun saveEval(
        @Path("unitKey") unitKey: String,
        @Path("itemId") itemId: Int,
        @Body body: SaveEvalRequest,
    ): Response<ApiResponse<Unit>>

    @POST("api/mobile/v1/judge/evaluation-lists/{unitKey}/{itemId}/approve")
    suspend fun approveEval(
        @Path("unitKey") unitKey: String,
        @Path("itemId") itemId: Int,
    ): Response<ApiResponse<Unit>>

    @POST("api/mobile/v1/chief-judge/evaluation-lists/{unitKey}/{itemId}/chief-approve")
    suspend fun chiefApprove(
        @Path("unitKey") unitKey: String,
        @Path("itemId") itemId: Int,
    ): Response<ApiResponse<Unit>>

    @POST("api/mobile/v1/chief-judge/evaluation-lists/{unitKey}/{itemId}/reopen")
    suspend fun chiefReopen(
        @Path("unitKey") unitKey: String,
        @Path("itemId") itemId: Int,
    ): Response<ApiResponse<Unit>>

    @GET("api/mobile/v1/judge/incomplete-tasks")
    suspend fun incompleteTasks(): Response<ApiResponse<Unit>>

    @GET("api/mobile/v1/notifications")
    suspend fun notifications(): Response<ApiResponse<Unit>>

    @POST("api/mobile/v1/notifications/{id}/read")
    suspend fun markNotificationRead(@Path("id") id: Int): Response<ApiResponse<Unit>>

    @POST("api/mobile/v1/sync/push")
    suspend fun syncPush(@Body body: SyncPushRequest): Response<ApiResponse<Unit>>
}
