from django.shortcuts import render

# Create your views here.
from django_redis import get_redis_connection
from rest_framework import status
from rest_framework.decorators import action
from rest_framework.generics import CreateAPIView, RetrieveAPIView, UpdateAPIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from rest_framework.views import APIView
from rest_framework.viewsets import ModelViewSet

from areas.serializers import AddressTitleSerializer, UserAddressSerializer
from carts.utils import merge_cart_cookie_to_redis
from goods.models import SKU
from goods.serializers import SKUSerializer
from . import constants
from .models import User, Address
from .serializers import CreateUserSerializer, UserDetailSerializer, EmailSerializer, AddUserBrowsingHistorySerializer

from rest_framework.status import HTTP_201_CREATED
from rest_framework_jwt.views import ObtainJSONWebToken


#判断用户名是否存在
# GET usernames/(?P<username>\w{5,20})/count/
class UsernameCountView(APIView):
    def get(self,request,username):
        count = User.objects.filter(username = username).count()
        data = {
            'username':username,
            'count':count
        }
        return Response(data)

#判断手机号是否存在
# GET mobiles/(?P<mobile>1[3-9]\d{9})/count/
class MobileCountView(APIView):
    def get(self,request,mobile):
        count = User.objects.filter(mobile=mobile).count()
        data = {
            'mobile':mobile,
            'count':count
        }
        return Response(data)

#注册接口
# POST /users/
class UserView(CreateAPIView):
    serializer_class = CreateUserSerializer

# 用户信息接口
# GET /user/
class UserDetailView(RetrieveAPIView):
    serializer_class = UserDetailSerializer
    permission_classes = [IsAuthenticated]
    def get_object(self,*args,**kwargs):
        return self.request.user

#发送验证邮件接口
# PUT /email/
class EmailView(UpdateAPIView):
    serializer_class = EmailSerializer
    permission_classes = [IsAuthenticated]

    def get_object(self,*args,**kwargs):
        return self.request.user

#验证邮箱链接
#GET /emails/verification/?token=xxx
class VerifyEmailView(APIView):
    def get(self,request):
        token = request.query_params.get('token')
        if not token:
            return Response({'message':'缺少token'},status = status.HTTP_400_BAD_REQUEST)
        user = User.check_verify_email_token(token)
        if user is None:
            return Response({'message':'链接信息无效'},status = status.HTTP_400_BAD_REQUEST)
        else:
            user.email_active = True
            user.save()
            return Response({'message': 'OK'})

class AddressViewSet(ModelViewSet):
    """用户地址增删改查"""
    serializer_class = UserAddressSerializer
    permissions = [IsAuthenticated]
    def get_queryset(self):
        return Address.objects.filter(user = self.request.user,is_deleted=False)
        # return self.request.user.addresses.filter(is_deleted=False)

    # def get_queryset(self):
    #     return self.request.user.addresses.filter(is_deleted=False)
    #GET /addresses/
    def list(self, request, *args, **kwargs):
        quert_set = self.get_queryset()
        serializer = self.get_serializer(quert_set,many = True)
        user = self.request.user
        return Response({
            'user_id':user.id,
            'default_address_id':user.default_address.id,
            'limit':constants.USER_ADDRESS_COUNTS_LIMIT,
            'addresses':serializer.data
        })

    # POST /addresses/
    def create(self, request, *args, **kwargs):
        """
            保存用户地址数据
        """
        # 检查用户地址数据数目不能超过上限
        count = request.user.addresses.count()
        if count >= constants.USER_ADDRESS_COUNTS_LIMIT:
            return Response({'message': '保存地址数据已达到上限'}, status=status.HTTP_400_BAD_REQUEST)
        return super().create(request,*args, **kwargs)

    # delete /addresses/<pk>/
    def destroy(self, request, *args, **kwargs):
        """删除"""
        address = self.get_object()
        address.is_deleted = True
        address.save()
        return Response(status=status.HTTP_204_NO_CONTENT)

    # put /addresses/pk/status/
    @action(methods = ['put'],detail = True)
    def status(self,request,pk = None):
        """设置默认地址"""
        address = self.get_object()
        user = self.request.user
        user.default_address = address
        user.save()
        return Response({'message':'OK'},status=status.HTTP_200_OK)

    # put /addresses/pk/title/
    #需要请求体参数title
    @action(methods=['put'],detail=True)
    def title(self,request,pk = None):
        """修改标题"""
        address = self.get_object()
        serializer = AddressTitleSerializer(address,data = request.data)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data)

# POST /browse_histories/
class UserBrowsingHistoryView(CreateAPIView):
    serializer_class = AddUserBrowsingHistorySerializer
    permission_classes = [IsAuthenticated]
    def get(self,request):
        user_id = request.user.id
        redis_conn =  get_redis_connection('history')
        history = redis_conn.lrange('history_%s' %user_id,0,constants.USER_BROWSING_HISTORY_COUNTS_LIMIT)
        skus = []
        for sku_id in history:
            sku = SKU.objects.get(id = sku_id)
            skus.append(sku)
        s = SKUSerializer(skus,many = True)
        return Response(s.data)

class UserAuthorizeView(ObtainJSONWebToken):
    """
    用户认证
    """
    def post(self, request, *args, **kwargs):
        # 调用父类的方法，获取drf jwt扩展默认的认证用户处理结果
        response = super().post(request, *args, **kwargs)

        # 仿照drf jwt扩展对于用户登录的认证方式，判断用户是否认证登录成功
        # 如果用户登录认证成功，则合并购物车
        serializer = self.get_serializer(data=request.data)
        if serializer.is_valid():
            user = serializer.validated_data.get('user')
            response = merge_cart_cookie_to_redis(request, user, response)

        return response
